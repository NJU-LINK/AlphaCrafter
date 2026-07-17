import os
import sys
import json
import threading
import contextlib
from datetime import datetime
from openai import OpenAI
from typing import List, Dict, Any, Optional, Callable, Union, Tuple
from pathlib import Path

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from ..toolkit.base import BaseTool
from ..skills.base import BaseSkill


class Agent:
    """
    Base agent class for OpenAI Responses API with enhanced features.
    """
    
    def __init__(
        self,
        model_code: str,
        toolkit: List[BaseTool],
        skills: List[BaseSkill] = None,
        instructions: str = "",
        config_path: str = "../config/models.json",
        log_file: str = "../logs/agent.json",
        summary_interval: int = 20,
    ):
        """
        Initialize the agent.
        
        Args:
            model_code: Model identifier (e.g., "gpt-5")
            toolkit: List of tool instances inheriting from BaseTool
            skills: List of skill instances inheriting from BaseSkill
            instructions: System instructions template with {skills} placeholder
            config_path: Path to the models configuration JSON file
            log_file: Path to log file for metadata (JSON array format)
            summary_interval: Number of iterations between summaries (default: 20)
        """
        self.model_code = model_code
        self.toolkit = toolkit
        self.skills = skills or []
        self.instructions_template = instructions
        self.config_path = config_path
        self.log_file = log_file
        self.summary_interval = summary_interval
        
        # Load model configuration
        self.model_config = self._load_model_config()
        
        # Get producer from config
        self.producer = self.model_config.get("producer", "OpenAI")
        
        # Initialize OpenAI client
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_URL"),
            timeout=1800
        )
        
        # Extract tool descriptions based on producer and implementations
        self.tools = [tool.get_description(producer=self.producer) for tool in toolkit]
        self.function_map = {tool.get_name(): tool.get_implementation() for tool in toolkit}
        
        # Build instructions message with skills injected
        self.instructions = self._build_instructions()
        
        print(f"✅ Agent initialized with model: {model_code}")
        print(f"📦 Loaded tools: {list(self.function_map.keys())}")
        print(f"📚 Loaded skills: {[skill.get_name() for skill in self.skills]}")
        print(f"⚙️ Summary interval: {summary_interval} iterations")
        
        # Load existing logs and append initialization entry
        self._append_log({
            "event": "agent_init",
            "model": model_code,
            "tools": list(self.function_map.keys()),
            "skills": [skill.get_name() for skill in self.skills],
            "instructions_length": len(self.instructions),
            "summary_interval": summary_interval,
            "timestamp": datetime.now().isoformat()
        })
    
    def _load_existing_logs(self) -> List[Dict[str, Any]]:
        """Load existing log entries from file."""
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    else:
                        print(f"⚠️ Warning: {self.log_file} does not contain a list, starting fresh")
                        return []
            except (json.JSONDecodeError, IOError) as e:
                print(f"⚠️ Warning: Could not read existing log file: {e}, starting fresh")
                return []
        return []
    
    def _append_log(self, entry: Dict[str, Any]):
        """Append log entry to file (preserves existing entries)."""
        # Load existing logs
        existing_logs = self._load_existing_logs()
        
        # Append new entry
        existing_logs.append(entry)
        
        # Write back to file
        log_dir = Path(self.log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(existing_logs, f, indent=2, ensure_ascii=False, default=str)
    
    def _build_instructions(self) -> str:
        """Build instructions by injecting skills into template"""
        if not self.instructions_template:
            return ""
        
        # Format skills information
        if self.skills:
            skills_text = "\n\nAvailable Skills:\n"
            for skill in self.skills:
                skills_text += f"Name: {skill.get_name()}\n"
                skills_text += f"Description: {skill.get_description()}\n"
                skills_text += f"Details: {skill.get_details()}\n"
        else:
            skills_text = "\n\nNo skills available."
        
        # Inject into template
        try:
            instructions = self.instructions_template.format(skills=skills_text)
        except KeyError:
            instructions = self.instructions_template + skills_text
        
        return instructions
    
    def _load_model_config(self) -> Dict[str, Any]:
        """Load configuration for the specified model from JSON file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                all_configs = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"❌ Model config file not found: {self.config_path}")
        except json.JSONDecodeError:
            raise ValueError(f"❌ Invalid JSON format in config file: {self.config_path}")
        
        if self.model_code not in all_configs:
            available = list(all_configs.keys())
            raise ValueError(
                f"❌ Model '{self.model_code}' not found in config. "
                f"Available models: {available}"
            )
        
        return all_configs[self.model_code]
    
    def _calculate_costs(self, input_tokens: int, output_tokens: int) -> Dict[str, float]:
        """
        Calculate input and output costs based on model configuration.
        Costs are assumed to be per million tokens.
        """
        cost_per_million_input = self.model_config.get("cost", {}).get("input", 0)
        cost_per_million_output = self.model_config.get("cost", {}).get("output", 0)
        
        input_cost = input_tokens * cost_per_million_input / 1_000_000
        output_cost = output_tokens * cost_per_million_output / 1_000_000
        
        return {
            "input_cost": round(input_cost, 8),
            "output_cost": round(output_cost, 8),
            "total_cost": round(input_cost + output_cost, 8)
        }
    
    def _log_metadata(self, result: Dict[str, Any], iteration: int):
        """Log interaction metadata to file as JSON array."""
        metadata = {
            "event": "iteration_complete",
            "timestamp": datetime.now().isoformat(),
            "iteration": iteration,
            "model": self.model_code,
            "output": result.get("output", []),
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
            "total_cost": result.get("total_cost", 0),
            "tool_calls": [
                {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                    "call_id": tc["call_id"],
                } for tc in result.get("tool_calls", [])
            ],
            "interrupted": result.get("interrupted", False)
        }
        
        self._append_log(metadata)
    
    def _summarize(self, current_input: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
        """
        Use the model to summarize what happened in this step.
        
        Args:
            current_input: The input list before this step
            
        Returns:
            Tuple containing (summary string, cost information)
        """
        try:
            MEMORY_INSTRUCTION = """You are a helpful assistant that produces step summaries. 
    Keep the summary concise, but explicitly include:
    - Key historical information that informs current decisions
    - Critical context that would otherwise be lost in a brief recap
    - The logical flow of recent actions and tool calls"""

            response = self.client.responses.create(
                model=self.model_code,
                input=current_input,
                instructions=MEMORY_INSTRUCTION,
            )
            
            # Extract token usage
            usage = getattr(response, "usage", {})
            input_tokens = getattr(usage, "input_tokens", 0)
            output_tokens = getattr(usage, "output_tokens", 0)
            
            # Calculate costs
            costs = self._calculate_costs(input_tokens, output_tokens)
            
            # Log memory usage to file
            self._append_log({
                "event": "memory_summary",
                "timestamp": datetime.now().isoformat(),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "input_cost": costs["input_cost"],
                "output_cost": costs["output_cost"],
                "total_cost": costs["total_cost"],
                "summary_length": len(response.output_text)
            })
            
            # Print to console
            print(f"📝 Memory summary generated - {output_tokens} tokens, ${costs['total_cost']:.6f}")
            
            return response.output_text, costs
            
        except Exception as e:
            print(f"Failed to generate summary: {e}")
            return "Step completed.", {"input_cost": 0, "output_cost": 0, "total_cost": 0}
    
    def get_response(self, input: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Call OpenAI Responses API and return detailed results.
        
        Args:
            input_list: Message list following OpenAI input format
            
        Returns:
            Dictionary containing response details
        """
        print(f"📤 API Request - {len(input)} messages")
        
        # Call API
        response = self.client.responses.create(
            model=self.model_code,
            tools=self.tools,
            input=input,
            instructions=self.instructions,
            parallel_tool_calls=False,
        )

        # Extract token usage
        usage = getattr(response, "usage", {})
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
        
        # Calculate costs
        costs = self._calculate_costs(input_tokens, output_tokens)
        
        # Extract tool calls
        tool_calls = []
        for item in response.output:
            if item.type == "function_call":
                tool_calls.append({
                    "name": item.name,
                    "arguments": json.loads(item.arguments) if item.arguments else {},
                    "call_id": item.call_id
                })
        
        result = {
            "input": input,
            "output": response.output,
            "output_text": response.output_text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_cost": costs["total_cost"],
            "tool_calls": tool_calls,
            "interrupted": False
        }
        
        print(f"📥 API Response - {output_tokens} tokens, ${costs['total_cost']:.6f}")
        if tool_calls:
            print(f"🔧 Tool calls: {[tc['name'] for tc in tool_calls]}")
        
        return result
    
    @contextlib.contextmanager
    def _run_context(self):
        """Context manager for run execution"""
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        start_time = datetime.now()
        
        # Log run start
        self._append_log({
            "event": "run_start",
            "run_id": run_id,
            "timestamp": start_time.isoformat(),
            "model": self.model_code
        })
        
        try:
            yield run_id
        finally:
            # Log run end
            duration = (datetime.now() - start_time).total_seconds()
            self._append_log({
                "event": "run_end",
                "run_id": run_id,
                "duration_seconds": round(duration, 2),
                "timestamp": datetime.now().isoformat()
            })
    
    def run(
        self, 
        initial_input: List[Dict[str, Any]], 
        max_iterations: int = 100,
        finish_check: Optional[Callable[[], bool]] = None,
        stop_event: Optional[threading.Event] = None
    ) -> Dict[str, Any]:
        """
        Run the agent with automatic multi-turn tool handling.
        
        Args:
            initial_input: Initial input message list
            max_iterations: Maximum number of iterations to prevent infinite loops
            finish_check: Optional function that takes no arguments and returns 
                        True if the run should finish, False to continue
            stop_event: Optional threading.Event to signal early termination
            
        Returns:
            Dictionary containing the final result and summary information
        """
        
        with self._run_context():
            current_input = initial_input.copy()
            iteration = 0
            total_cost = 0
            all_tool_calls = []
            last_result = None
            
            print("=" * 60)
            print("🚀 AGENT RUN STARTED")
            print("=" * 60)
            
            while iteration < max_iterations:
                if stop_event and stop_event.is_set():
                    print("⏹️ Stop event triggered - terminating agent run")
                    break
                
                iteration += 1
                print(f"\n{'─' * 40}")
                print(f"🔄 Iteration {iteration}/{max_iterations}")
                print(f"{'─' * 40}")
                
                # Get response from model
                result = self.get_response(current_input)
                last_result = result
                
                # Update metadata with iteration
                self._log_metadata(result, iteration)
                
                # Update totals
                total_cost += result["total_cost"]
                all_tool_calls.extend(result["tool_calls"])
                
                # Check finish condition if provided
                if finish_check and finish_check():
                    print("✅ Finish condition met")
                    break
                
                # Check stop signal again after finish_check
                if stop_event and stop_event.is_set():
                    print("⏹️ Stop event triggered - terminating agent run")
                    break
                
                # If no tool calls, end the run
                if not result["tool_calls"]:
                    print("✅ No more tool calls required - ending run")
                    break
                
                print(f"⚙️ Executing {len(result['tool_calls'])} tool call(s)...")
                
                # Add model response to input for context (only function_calls)
                for item in result["output"]:
                    if item.type == "function_call":
                        current_input.append(item)
                
                # Execute tool calls and append results
                for tool_call in result["tool_calls"]:
                    if stop_event and stop_event.is_set():
                        print("⏹️ Stop event triggered during tool execution")
                        break
                    
                    func_name = tool_call["name"]
                    arguments = tool_call["arguments"]
                    call_id = tool_call["call_id"]
                    
                    print(f"  ▶️ {func_name}({arguments})")
                    
                    if func_name not in self.function_map:
                        error_msg = f"Unknown tool function: {func_name}"
                        print(f"  ❌ {error_msg}")
                        
                        # Log error metadata
                        self._append_log({
                            "event": "tool_error",
                            "timestamp": datetime.now().isoformat(),
                            "iteration": iteration,
                            "tool": func_name,
                            "error": error_msg
                        })
                        
                        raise ValueError(error_msg)
                    
                    # Execute the tool
                    func = self.function_map[func_name]
                    
                    try:
                        output = func(**arguments)
                        print(f"  ✅ {func_name} output: \n\n {output}")
                    except Exception as e:
                        output = f"Tool execution error: {str(e)}"
                        print(f"  ❌ {func_name} failed: {e}")
                        
                        # Log error metadata
                        self._append_log({
                            "event": "tool_error",
                            "timestamp": datetime.now().isoformat(),
                            "iteration": iteration,
                            "tool": func_name,
                            "error": str(e)
                        })
                    
                    # Add tool output to input list
                    current_input.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps({func_name: output})
                    })
                
                if stop_event and stop_event.is_set():
                    break
                
                # Generate summary based on interval
                if iteration % self.summary_interval == 0:
                    print(f"📝 Reached {iteration} iterations, generating summary...")
                    
                    summary, memory_costs = self._summarize(current_input)
                    total_cost += memory_costs["total_cost"]
                    
                    # Log step summary
                    self._append_log({
                        "event": "interval_summary",
                        "timestamp": datetime.now().isoformat(),
                        "iteration": iteration,
                        "summary": summary,
                        "interval": self.summary_interval,
                        "tools_executed_in_interval": [tc["name"] for tc in result["tool_calls"]]
                    })
                    
                    # Clear input and add summary
                    print(f"🧹 Clearing input and adding interval summary...")
                    current_input = [
                        {
                            "role": "user",
                            "content": f"Progress summary after {iteration} iterations: {summary}\n\nContinue with the task."
                        }
                    ]
                    
                    print(f"📋 Interval summary: {summary}")
            
            if iteration >= max_iterations:
                print(f"⚠️ Max iterations ({max_iterations}) reached")
            
            # Final summary
            print("\n" + "=" * 60)
            print("📊 RUN SUMMARY")
            print("=" * 60)
            print(f"Iterations: {iteration}")
            print(f"Total cost: ${total_cost:.6f}")
            print(f"Total tool calls: {len(all_tool_calls)}")
            if all_tool_calls:
                tools_used = set(tc['name'] for tc in all_tool_calls)
                print(f"Tools used: {tools_used}")
            print("=" * 60)
            
            # Determine if interrupted by stop event
            interrupted = stop_event.is_set() if stop_event else False
            
            # Prepare return value
            final_state = {
                "success": last_result is not None,
                "input": current_input,
                "output_text": last_result.get("output_text") if last_result else None,
                "interrupted": interrupted,
                "stop_event_triggered": interrupted
            }
            
            # Log run completion
            self._append_log({
                "event": "run_complete",
                "timestamp": datetime.now().isoformat(),
                "total_iterations": iteration,
                "total_cost": total_cost,
                "total_tool_calls": len(all_tool_calls),
                "tools_used": list(tools_used) if all_tool_calls else [],
                "final_state": final_state,
                "interrupted": interrupted
            })

            print(f"🚀 Agent run completed. Output: {final_state.get('output_text')}")
            
            return final_state