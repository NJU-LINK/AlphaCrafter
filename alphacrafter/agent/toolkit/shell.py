# toolkit/shell_tool.py
import sys
import os
import subprocess
import shlex
import signal
import time
from typing import Dict, Any, Callable, Optional, List
from .base import BaseTool


class ShellTool(BaseTool):
    """Tool for executing shell commands from a whitelist."""
    
    # Default whitelist of allowed commands
    DEFAULT_WHITELIST = [
        'ls', 'python', 'echo', 'tail', 'grep'
    ]
    
    def __init__(
        self, 
        whitelist: Optional[List[str]] = None,
        working_dir: Optional[str] = '.',
        timeout: int = 300,
        max_output_length: int = 6000,
    ):
        """
        Initialize the shell tool.
        
        Args:
            whitelist: List of allowed commands (defaults to DEFAULT_WHITELIST)
            working_dir: Working directory for command execution
            timeout: Maximum execution time in seconds
            max_output_length: Maximum length of output to return
        """
        self.whitelist = whitelist or self.DEFAULT_WHITELIST.copy()
        self.working_dir = working_dir or os.getcwd()
        self.timeout = timeout
        self.max_output_length = max_output_length
    
    def get_name(self) -> str:
        return "shell"
    
    def _is_command_allowed(self, command: str) -> tuple:
        """
        Check if the command is in the whitelist.
        
        Returns:
            Tuple of (is_allowed, command_name, error_message)
        """
        # Parse the command to get the base command
        try:
            parts = shlex.split(command)
            if not parts:
                return False, None, "Empty command"
            
            base_cmd = parts[0]
            
            # Check if base command is in whitelist
            if base_cmd in self.whitelist:
                return True, base_cmd, None
            
            # Check for path variations (e.g., /bin/ls, ./script.py)
            base_name = os.path.basename(base_cmd)
            if base_name in self.whitelist:
                return True, base_name, None
            
            return False, base_cmd, f"Command '{base_cmd}' is not in the whitelist. Allowed commands: {', '.join(self.whitelist)}"
            
        except Exception as e:
            return False, None, f"Error parsing command: {str(e)}"
    
    def _truncate_output(self, output: str) -> str:
        """Truncate output if it's too long."""
        if len(output) > self.max_output_length:
            return output[:self.max_output_length] + f"\n... (output truncated, {len(output) - self.max_output_length} more characters)"
        return output
    
    def _kill_process_tree(self, process: subprocess.Popen) -> None:
        """Kill the entire process tree to ensure cleanup."""
        try:
            # Use process group to kill all child processes
            if sys.platform == 'win32':
                # Windows: use taskkill
                subprocess.run(
                    f'taskkill /F /T /PID {process.pid}',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # Unix: send SIGKILL to process group
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            # Fallback: just terminate the main process
            try:
                process.terminate()
            except Exception:
                pass
    
    def get_implementation(self) -> Callable:
        def shell(command: str) -> str:
            """
            Execute a shell command from the whitelist.
            
            Args:
                command: Shell command to execute (e.g., "ls -la", "python script.py")
                
            Returns:
                String containing command output or error message
            """
            # Check if command is allowed
            is_allowed, cmd_name, error_msg = self._is_command_allowed(command)
            if not is_allowed:
                return f"❌ {error_msg}"
            
            process = None
            try:
                # Unix: create new process group so we can kill all children
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=self.working_dir,
                    env=os.environ.copy(),
                    preexec_fn=os.setsid  # Create new process group
                )
                
                # Use a more robust timeout mechanism with polling
                start_time = time.time()
                stdout_lines = []
                stderr_lines = []
                
                # Set non-blocking reads (simplified approach)
                import select
                import threading
                
                # Use threading to read output without blocking
                def read_stream(stream, lines_list):
                    try:
                        for line in iter(stream.readline, ''):
                            lines_list.append(line)
                    except Exception:
                        pass
                
                stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines))
                stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines))
                stdout_thread.daemon = True
                stderr_thread.daemon = True
                stdout_thread.start()
                stderr_thread.start()
                
                # Wait for process with timeout
                while True:
                    elapsed = time.time() - start_time
                    if elapsed >= self.timeout:
                        # Timeout reached - kill the entire process tree
                        self._kill_process_tree(process)
                        return f"❌ Command timed out after {self.timeout} seconds\nPartial stderr:\n{self._truncate_output(''.join(stderr_lines))}"
                    
                    # Check if process has finished
                    if process.poll() is not None:
                        break
                    
                    time.sleep(0.1)  # Small sleep to avoid busy waiting
                
                # Wait for threads to finish reading
                stdout_thread.join(timeout=1)
                stderr_thread.join(timeout=1)
                
                stdout = ''.join(stdout_lines)
                stderr = ''.join(stderr_lines)
                
                # Check return code
                if process.returncode != 0:
                    error_msg = f"Command failed with exit code {process.returncode}"
                    if stderr:
                        error_msg += f"\n{self._truncate_output(stderr)}"
                    return f"❌ {error_msg}"
                
                # Build result message
                result_parts = []
                
                if stdout:
                    result_parts.append(f"✅ Output:\n{self._truncate_output(stdout.strip())}")
                
                if stderr:
                    result_parts.append(f"⚠️ Warnings:\n{self._truncate_output(stderr.strip())}")
                
                if not result_parts:
                    return f"✅ Command executed successfully (no output)"
                
                return "\n\n".join(result_parts)
                
            except Exception as e:
                return f"❌ Error executing command: {str(e)}"
            finally:
                # Ensure process is cleaned up
                if process is not None and process.poll() is None:
                    self._kill_process_tree(process)
        
        return shell
    
    def get_description(self, producer: str = "OpenAI") -> Dict[str, Any]:
        """
        Return tool description based on the producer.
        
        Args:
            producer: The model producer (currently supports "OpenAI")
        """
        if producer == "OpenAI":
            return {
                "type": "function",
                "name": self.get_name(),
                "description": f"Execute shell commands from a restricted whitelist. Allowed commands: {', '.join(self.whitelist)}. Use this for file operations, running scripts, and system information. Output will be truncated if too long. Commands have a hard timeout of {self.timeout} seconds and will be forcibly terminated if exceeded.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": f"Shell command to execute. Must start with one of: {', '.join(self.whitelist)}. Examples: 'ls -la', 'python script.py', 'pwd', 'echo hello'"
                        }
                    },
                    "required": ["command"]
                }
            }
        else:
            raise ValueError(f"Unsupported producer: {producer}")