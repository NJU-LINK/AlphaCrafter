import os
import sys
import json
import time
import argparse
import yaml
import signal
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.openai.agent import Agent

from agent.instructions import (
    QUANTITATIVE_TRADING_INSTRUCTION_A,
    MINER_INSTRUCTION,
    SCREENER_INSTRUCTION,
    TRADER_INSTRUCTION
)
from agent.toolkit import (
    ReadFileTool, WriteFileTool, ShellTool, 
    GetStockDataTool, GetIndexDataTool, StepTool,
    BacktestTool, SearchFactorTool, GetFinancialStatementsTool, GetNewsTool
)
from agent.skills import (
    QuantitativeTradingSkill, 
    FactorMiningSkill,
    FactorScreeningSkill,
    StrategyRegistrationSkill,
    PositionManagementSkill
)

from alphacrafter.sim.utils import finish_check, get_date_str

load_dotenv()


@dataclass
class CycleRecord:
    """Record of a single cycle's outputs from all agents."""
    cycle: int
    miner_outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # {miner_id: {output_text, success}}
    screener_output: str = ""
    trader_output: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class Launcher:
    """Orchestrates the iterative workflow of Miner, Screener, and Trader agents."""
    
    def __init__(self, session_id: str, config_path: str = "config.yaml", resume: bool = False):
        """
        Initialize the launcher with a session ID and configuration.
        
        Args:
            session_id: Session identifier for workspace
            config_path: Path to configuration YAML file
            resume: Whether to resume from previous workflow state
        """
        self.session_id = session_id
        self.resume = resume
        self.workspace_path = None
        
        # Load configuration
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        # Extract configuration values
        self.max_cycles = self.config['workflow']['max_cycles']
        self.miner_count = self.config['miner']['count']
        self.miner_ids = self.config['miner']['ids'][:self.miner_count]
        
        # Extract model configurations for each agent type
        self.miner_model_config = self.config['miner']['model']
        self.screener_model_config = self.config['screener']['model']
        self.trader_model_config = self.config['trader']['model']
        
        # Agent instances
        self.miner_agents: Dict[str, Agent] = {}
        self.screener_agent = None
        self.trader_agent = None
        
        # Thread lock for thread-safe operations
        self.lock = threading.Lock()
        
        # Stop event for graceful interruption
        self.stop_event = threading.Event()
        self.original_sigint_handler = None
        
        # History storage
        self.cycle_records: List[CycleRecord] = []
        
        # Logging
        self.log_path = self.config['logging']['workflow_log']
        self.miner_log_pattern = self.config['logging']['miner_log_pattern']
        self.screener_log_path = self.config['logging']['screener_log']
        self.trader_log_path = self.config['logging']['trader_log']
        
        # Store last inputs for resume mode
        self.last_miner_inputs: Dict[str, Optional[List[Dict[str, str]]]] = {
            miner_id: None for miner_id in self.miner_ids
        }
        self.last_screener_input = None
        self.last_trader_input = None
        
        # Load additional info
        self.additional_info = self.config.get('additional_info', '')
        
    def _setup_signal_handler(self):
        """Setup signal handler for graceful interruption."""
        def signal_handler(sig, frame):
            print("\n\n⚠️  Interrupt received (Ctrl+C), stopping workflow gracefully...")
            self.stop_event.set()
            print("⏹️ Stop signal sent to all agents. Waiting for them to finish...")
        
        self.original_sigint_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, signal_handler)
        print("✅ Signal handler set up for graceful interruption")
    
    def _restore_signal_handler(self):
        """Restore original signal handler."""
        if self.original_sigint_handler:
            signal.signal(signal.SIGINT, self.original_sigint_handler)
            print("✅ Signal handler restored")
    
    def _get_session_workspace(self) -> str:
        """Get existing session workspace path."""
        base_dir = os.path.dirname(os.path.dirname(__file__))
        sandbox_path = os.path.join(base_dir, 'alphacrafter/sandbox')
        session_path = os.path.join(sandbox_path, self.session_id)
        workspace_path = os.path.join(session_path, 'workspace')
        
        if not os.path.exists(session_path):
            raise FileNotFoundError(f"Session directory not found: {session_path}")
        if not os.path.exists(workspace_path):
            raise FileNotFoundError(f"Workspace directory not found: {workspace_path}")
        
        print(f"Using existing session: {self.session_id}")
        print(f"Workspace path: {workspace_path}")
        
        return workspace_path
    
    def _setup_workspace(self):
        """Setup workspace environment."""
        os.chdir(self.workspace_path)
        if self.workspace_path not in sys.path:
            sys.path.insert(0, self.workspace_path)
        
        print(f"\nWorking in: {self.workspace_path}")
        print("\nCurrent workspace contents:")
        for item in os.listdir('.'):
            print(f"  - {item}")
    
    def _load_last_input_from_agent_log(self, agent_log_path: str) -> Optional[List[Dict[str, str]]]:
        """Extract the last input from an agent's log file and convert to simple user message."""
        if not os.path.exists(agent_log_path):
            return None
        
        try:
            with open(agent_log_path, 'r', encoding='utf-8') as f:
                entries = json.load(f)
                if not isinstance(entries, list):
                    entries = [entries]
        except Exception as e:
            print(f"Error reading {agent_log_path}: {e}")
            return None
        
        # Find the last successful run with input
        for entry in reversed(entries):
            if entry.get('event') == 'run_complete':
                final_state = entry.get('final_state', {})
                if final_state.get('success') and final_state.get('input'):
                    original_input = final_state['input']
                    return self._aggregate_input_to_user_message(original_input)
        
        return None

    def _aggregate_input_to_user_message(self, input_array: List) -> List[Dict[str, str]]:
        """Aggregate various input elements into a single user message."""
        if not input_array:
            return [{"role": "user", "content": ""}]
        
        aggregated_content = "you are resuming from the previous session: " + str(input_array)
        return [{"role": "user", "content": aggregated_content}]
    
    def _load_previous_workflow_state(self) -> Optional[int]:
        """Load previous workflow state from logs BEFORE agent initialization."""
        if not os.path.exists(self.log_path):
            print("No previous workflow log found. Starting fresh.")
            return None
        
        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                entries = json.load(f)
                if not isinstance(entries, list):
                    entries = [entries]
        except Exception as e:
            print(f"Error reading workflow log: {e}")
            return None
        
        if not entries:
            return None
        
        # Group entries by cycle
        cycles = {}
        for entry in entries:
            cycle_num = entry.get('cycle')
            if cycle_num not in cycles:
                cycles[cycle_num] = {'miner': [], 'screener': None, 'trader': None}
            phase = entry.get('phase')
            if phase and phase.startswith('miner_'):
                cycles[cycle_num]['miner'].append(entry)
            elif phase in ['screener', 'trader']:
                cycles[cycle_num][phase] = entry
        
        # Find the last complete cycle
        last_complete_cycle = None
        for cycle_num in sorted(cycles.keys()):
            cycle_data = cycles[cycle_num]
            if (cycle_data['miner'] and all(m.get('success') for m in cycle_data['miner']) and
                cycle_data['screener'] and cycle_data['screener'].get('success') and
                cycle_data['trader'] and cycle_data['trader'].get('success')):
                last_complete_cycle = cycle_num
        
        if last_complete_cycle is not None:
            print(f"Found previous workflow state. Last complete cycle: {last_complete_cycle}")
            
            # Reconstruct cycle records
            for cycle_num in sorted(cycles.keys()):
                if cycle_num <= last_complete_cycle:
                    cycle_data = cycles[cycle_num]
                    record = CycleRecord(cycle=cycle_num)
                    
                    # Reconstruct miner outputs
                    for miner_entry in cycle_data['miner']:
                        miner_id = miner_entry.get('phase', '').replace('miner_', '')
                        record.miner_outputs[miner_id] = {
                            'output_text': miner_entry.get('output_text', ''),
                            'success': miner_entry.get('success', False)
                        }
                    
                    record.screener_output = cycle_data['screener'].get('output_text', '') if cycle_data['screener'] else ''
                    record.trader_output = cycle_data['trader'].get('output_text', '') if cycle_data['trader'] else ''
                    self.cycle_records.append(record)
            
            return last_complete_cycle
        else:
            print("No complete cycles found in previous workflow. Starting fresh.")
            return None
    
    def _load_resume_inputs(self):
        """Load last inputs from agent logs BEFORE agent initialization."""
        if not self.resume:
            return
        
        print("\n" + "="*60)
        print("📂 LOADING RESUME INPUTS FROM LOGS")
        print("="*60)
        
        # Load last inputs from each miner's log
        for miner_id in self.miner_ids:
            miner_log_path = self.miner_log_pattern.format(miner_id=miner_id)
            self.last_miner_inputs[miner_id] = self._load_last_input_from_agent_log(miner_log_path)
            if self.last_miner_inputs[miner_id]:
                print(f"✅ Loaded last miner input for {miner_id} from {miner_log_path}")
            else:
                print(f"⚠️ No previous miner input found for {miner_id}")
        
        # Load screener and trader inputs
        self.last_screener_input = self._load_last_input_from_agent_log(self.screener_log_path)
        self.last_trader_input = self._load_last_input_from_agent_log(self.trader_log_path)
        
        if self.last_screener_input:
            print(f"✅ Loaded last screener input from {self.screener_log_path}")
        else:
            print(f"⚠️ No previous screener input found")
            
        if self.last_trader_input:
            print(f"✅ Loaded last trader input from {self.trader_log_path}")
        else:
            print(f"⚠️ No previous trader input found")
    
    def _create_miner_agent(self, miner_id: str) -> Agent:
        """Create and configure a single miner agent for factor discovery."""
        toolkit = [
            ReadFileTool(),
            WriteFileTool(),
            ShellTool(),
        ]
        
        skills = [QuantitativeTradingSkill(), FactorMiningSkill()]
        
        # Use MINER_INSTRUCTION with miner_id formatting
        miner_instruction = MINER_INSTRUCTION.format(miner_id=miner_id)
        
        agent = Agent(
            model_code=self.miner_model_config['code'],
            toolkit=toolkit,
            skills=skills,
            instructions=QUANTITATIVE_TRADING_INSTRUCTION_A + "\n\n" + miner_instruction + "\n\n" + self.additional_info,
            config_path=self.miner_model_config['config_path'],
            log_file=self.miner_log_pattern.format(miner_id=miner_id),
            summary_interval=15,
        )
        
        return agent
    
    def _create_screener_agent(self) -> Agent:
        """Create and configure screener agent for factor selection and ensemble construction."""
        toolkit = [
            ShellTool(),
            GetStockDataTool(),
            GetIndexDataTool(),
            SearchFactorTool(),
            GetFinancialStatementsTool(),
            GetNewsTool()
        ]
        
        skills = [FactorScreeningSkill()]
        
        agent = Agent(
            model_code=self.screener_model_config['code'],
            toolkit=toolkit,
            skills=skills,
            instructions=QUANTITATIVE_TRADING_INSTRUCTION_A + "\n\n" + SCREENER_INSTRUCTION + "\n\n" + self.additional_info,
            config_path=self.screener_model_config['config_path'],
            log_file=self.screener_log_path,
            summary_interval=15,
        )
        
        return agent
    
    def _create_trader_agent(self) -> Agent:
        """Create and configure trader agent for portfolio execution."""
        toolkit = [
            ReadFileTool(),
            WriteFileTool(),
            BacktestTool(),
            StepTool(),
        ]
        
        skills = [QuantitativeTradingSkill(), StrategyRegistrationSkill(), PositionManagementSkill()]
        
        agent = Agent(
            model_code=self.trader_model_config['code'],
            toolkit=toolkit,
            skills=skills,
            instructions=QUANTITATIVE_TRADING_INSTRUCTION_A + "\n\n" + TRADER_INSTRUCTION + "\n\n" + self.additional_info,
            config_path=self.trader_model_config['config_path'],
            log_file=self.trader_log_path,
            summary_interval=15,
        )
        
        return agent
    
    def _run_agent_phase(self, agent: Agent, context: str, phase_name: str, max_iterations: int = None) -> Dict[str, Any]:
        """Run a single agent phase with given context."""
        if max_iterations is None:
            # Determine max_iterations based on phase
            if phase_name.startswith('miner'):
                max_iterations = self.config['miner']['max_iterations']
            elif phase_name == 'screener':
                max_iterations = self.config['screener']['max_iterations']
            elif phase_name == 'trader':
                max_iterations = self.config['trader']['max_iterations']
            else:
                max_iterations = 100
        
        print(f"\n{'='*60}")
        print(f"🔬 {phase_name.upper()} PHASE")
        print(f"{'='*60}")
        
        input_messages = [{"role": "user", "content": context}] if context else [{"role": "user", "content": ""}]
        
        result = agent.run(
            input_messages, 
            max_iterations=max_iterations, 
            finish_check=finish_check,
            stop_event=self.stop_event  # Pass stop event for graceful interruption
        )
        
        print(f"\n{'='*60}")
        print(f"🔬 {phase_name.upper()} PHASE COMPLETED")
        print(f"{'='*60}")
        
        return result
    
    def _run_agent_phase_with_resume(self, agent: Agent, last_input: Optional[List[Dict[str, str]]], 
                                      context: str, phase_name: str, max_iterations: int = None) -> Dict[str, Any]:
        """Run an agent phase, using last_input if in resume mode and available."""
        if max_iterations is None:
            # Determine max_iterations based on phase
            if phase_name.startswith('miner'):
                max_iterations = self.config['miner']['max_iterations']
            elif phase_name == 'screener':
                max_iterations = self.config['screener']['max_iterations']
            elif phase_name == 'trader':
                max_iterations = self.config['trader']['max_iterations']
            else:
                max_iterations = 100
        
        if self.resume and last_input:
            print(f"\n{'='*60}")
            print(f"🔬 {phase_name.upper()} PHASE - RESUMING FROM LAST INPUT")
            print(f"{'='*60}")
            print(f"Using last input from previous run")
            
            result = agent.run(
                last_input, 
                max_iterations=max_iterations, 
                finish_check=finish_check,
                stop_event=self.stop_event  # Pass stop event for graceful interruption
            )
            
            print(f"\n{'='*60}")
            print(f"🔬 {phase_name.upper()} PHASE COMPLETED (RESUMED)")
            print(f"{'='*60}")
            
            return result
        else:
            return self._run_agent_phase(agent, context, phase_name, max_iterations)
    
    def _run_single_miner(self, miner_id: str, context: str, is_resume_cycle: bool = False) -> Dict[str, Any]:
        """Run a single miner agent and return its output as dict."""
        agent = self.miner_agents[miner_id]
        miner_phase_name = f"miner_{miner_id}"
        
        if is_resume_cycle:
            result = self._run_agent_phase_with_resume(
                agent,
                self.last_miner_inputs[miner_id],
                context,
                miner_phase_name
            )
        else:
            result = self._run_agent_phase(agent, context, miner_phase_name)
        
        miner_output = {
            'miner_id': miner_id,
            'output_text': result.get("output_text", ""),
            'success': result.get("success", False)
        }
        
        return miner_output
    
    def _run_all_miners_concurrently(self, context: str, is_resume_cycle: bool = False) -> Dict[str, Dict[str, Any]]:
        """Run all miner agents concurrently and collect results."""
        print(f"\n{'='*60}")
        print(f"🚀 RUNNING {len(self.miner_ids)} MINERS CONCURRENTLY")
        print(f"{'='*60}")
        
        miner_outputs = {}
        
        with ThreadPoolExecutor(max_workers=len(self.miner_ids)) as executor:
            # Submit all miner tasks
            future_to_miner = {
                executor.submit(self._run_single_miner, miner_id, context, is_resume_cycle): miner_id
                for miner_id in self.miner_ids
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_miner):
                miner_id = future_to_miner[future]
                try:
                    miner_output = future.result()
                    miner_outputs[miner_id] = miner_output
                    
                    print(f"\n--- ✅ Miner {miner_id} completed ---")
                    print(f"Output length: {len(miner_output['output_text'])}")
                    
                    # Log miner result
                    self._log_workflow_entry(0, f"miner_{miner_id}", {
                        'success': miner_output['success'],
                        'output_text': miner_output['output_text']
                    })
                    
                except Exception as e:
                    print(f"\n--- ❌ Miner {miner_id} failed: {e} ---")
                    miner_outputs[miner_id] = {
                        'miner_id': miner_id,
                        'output_text': f"Error: {str(e)}",
                        'success': False
                    }
        
        return miner_outputs
    
    def _should_terminate(self, result: Dict[str, Any]) -> bool:
        """Determine if workflow should terminate based on result."""
        # Check if stop event was triggered
        if self.stop_event.is_set():
            print("⏹️ Stop event triggered - terminating workflow")
            return True
        
        if result.get("interrupted", False):
            print("⏹️ Interrupted by user")
            return True
        
        if not result.get("success", False):
            print("❌ Phase failed")
            return True
        
        try:
            if finish_check():
                print("✅ finish_check returned True")
                return True
        except:
            pass
        
        return False
    
    def _log_workflow_entry(self, cycle: int, phase: str, result: Dict[str, Any]):
        """Append a workflow entry to JSON log file."""
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        
        entries = []
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, 'r', encoding='utf-8') as f:
                    entries = json.load(f)
                    if not isinstance(entries, list):
                        entries = [entries]
            except:
                entries = []
        
        entries.append({
            "cycle": cycle,
            "phase": phase,
            "timestamp": datetime.now().isoformat(),
            "success": result.get("success", False),
            "interrupted": result.get("interrupted", False),
            "stop_event_triggered": result.get("stop_event_triggered", False),
            "output_text": result.get("output_text", "")
        })
        
        with open(self.log_path, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=2, ensure_ascii=False, default=str)
    
    def _build_miner_context(self, miner_id: str) -> str:
        """Build context for a specific miner agent using only its own previous output."""
        context_parts = []
        
        # Add date information
        current_date = get_date_str()
        context_parts.append(f"Current date: {current_date}")
        
        # Add only this miner's previous output
        if self.cycle_records:
            last_record = self.cycle_records[-1]
            
            # Get this specific miner's previous output
            if miner_id in last_record.miner_outputs:
                previous_output = last_record.miner_outputs[miner_id]['output_text']
                context_parts.append(f"Your previous output: {previous_output}...")
        
        return "\n".join(context_parts) if context_parts else ""

    def _build_screener_context(self) -> str:
        """Build context for screener agent using all miner outputs and previous history."""
        context_parts = []
        
        # Add date information
        current_date = get_date_str()
        context_parts.append(f"Current date: {current_date}")
        
        if not self.cycle_records:
            return "\n".join(context_parts) if context_parts else ""
        
        last_record = self.cycle_records[-1]
        
        # Current cycle all miner outputs
        for miner_id, output in last_record.miner_outputs.items():
            context_parts.append(f"Miner {miner_id} output from current cycle: {output['output_text']}")
        
        # Previous cycle screener and trader outputs
        if len(self.cycle_records) >= 2:
            prev_record = self.cycle_records[-2]
            if prev_record.screener_output:
                context_parts.append(f"Previous screener agent output: {prev_record.screener_output}")
        
        return "\n\n".join(context_parts) if context_parts else ""

    def _build_trader_context(self) -> str:
        """Build context for trader agent using current screener output and previous history."""
        context_parts = []
        
        # Add date information
        current_date = get_date_str()
        context_parts.append(f"Current date: {current_date}")
        
        if not self.cycle_records:
            return "\n".join(context_parts) if context_parts else ""
        
        last_record = self.cycle_records[-1]
        
        # Current cycle screener output
        if last_record.screener_output:
            context_parts.append(f"Screener agent output from current cycle: {last_record.screener_output}")
        
        # Previous cycle trader output
        if len(self.cycle_records) >= 2:
            prev_record = self.cycle_records[-2]
            if prev_record.trader_output:
                context_parts.append(f"Previous trader agent output: {prev_record.trader_output}")
        
        return "\n\n".join(context_parts) if context_parts else ""
    
    def _run_single_cycle(self, cycle: int, is_resume_cycle: bool = False) -> bool:
        """Execute a single cycle with concurrent miners."""
        print("\n" + "█"*60)
        if is_resume_cycle:
            print(f"🔄 RESUME CYCLE {cycle}/{self.max_cycles}")
        else:
            print(f"🔄 CYCLE {cycle}/{self.max_cycles}")
        print("█"*60)
        
        record = CycleRecord(cycle=cycle)
        
        # Step 1: Run ALL Miner Agents concurrently
        miner_outputs = self._run_all_miners_concurrently("", is_resume_cycle)
        
        # Check if any miner failed
        all_miners_success = all(output['success'] for output in miner_outputs.values())
        if not all_miners_success:
            print("⚠️ Some miners failed, but continuing with available results")
        
        record.miner_outputs = miner_outputs
        
        # Print all miner outputs
        print(f"\n--- 🔄 Cycle {cycle} All Miner Outputs ---")
        for miner_id, output in miner_outputs.items():
            print(f"\n[{miner_id}]:")
            print(f"{output['output_text'][:200]}...")
        
        # Add record with miner outputs so screener can access them
        self.cycle_records.append(record)
        
        # Check if stop event was triggered during miner phase
        if self.stop_event.is_set():
            print("⏹️ Stop event triggered after miner phase - terminating cycle")
            return False
        
        # Step 2: Run Screener Agent
        screener_context = self._build_screener_context()
        screener_result = self._run_agent_phase_with_resume(
            self.screener_agent,
            self.last_screener_input if is_resume_cycle else None,
            screener_context,
            "screener",
            max_iterations=self.config['screener']['max_iterations']
        )
        record.screener_output = screener_result.get("output_text", "")
        
        print(f"\n--- 🔄 Cycle {cycle} Screener Output ---")
        print(f"{record.screener_output[:200]}...")
        
        self._log_workflow_entry(cycle, "screener", screener_result)
        
        if self._should_terminate(screener_result):
            return False
        
        # Update record with screener output
        self.cycle_records[-1] = record
        
        # Step 3: Run Trader Agent
        trader_context = self._build_trader_context()
        trader_result = self._run_agent_phase_with_resume(
            self.trader_agent,
            self.last_trader_input if is_resume_cycle else None,
            trader_context,
            "trader",
            max_iterations=self.config['trader']['max_iterations']
        )
        record.trader_output = trader_result.get("output_text", "")
        
        print(f"\n--- 🔄 Cycle {cycle} Trader Output ---")
        print(f"{record.trader_output[:200]}...")
        
        self._log_workflow_entry(cycle, "trader", trader_result)
        
        if self._should_terminate(trader_result):
            return False
        
        # Final update with trader output
        self.cycle_records[-1] = record
        
        print(f"\n💾 Cycle {cycle} completed with {len(miner_outputs)} miner(s)")
        
        return True
    
    def run(self) -> Dict[str, Any]:
        """Run the full iterative workflow with concurrent miners."""
        # Setup signal handler for graceful interruption
        self._setup_signal_handler()
        
        try:
            # Setup workspace
            self.workspace_path = self._get_session_workspace()
            self._setup_workspace()
            
            # IMPORTANT: Load resume inputs BEFORE creating agents
            if self.resume:
                self._load_resume_inputs()
                last_complete_cycle = self._load_previous_workflow_state()
            else:
                last_complete_cycle = None
            
            # Create all agents
            print(f"\n📊 Creating {len(self.miner_ids)} miner agents...")
            for miner_id in self.miner_ids:
                self.miner_agents[miner_id] = self._create_miner_agent(miner_id)
            
            self.screener_agent = self._create_screener_agent()
            self.trader_agent = self._create_trader_agent()
            
            # Handle resume mode workflow
            if self.resume and last_complete_cycle is not None:
                print("\n" + "="*60)
                print(f"🚀 RESUMING WORKFLOW from cycle {last_complete_cycle + 1} (max {self.max_cycles} cycles)")
                print("="*60)
                
                next_cycle = last_complete_cycle + 1
                should_continue = self._run_single_cycle(next_cycle, is_resume_cycle=True)
                
                if not should_continue:
                    print("Workflow terminated during resume cycle.")
                    return {
                        "success": True,
                        "total_cycles": len(self.cycle_records),
                        "cycle_records": [asdict(r) for r in self.cycle_records]
                    }
                
                current_cycle = next_cycle
            else:
                if self.resume:
                    print("\nNo previous workflow state found. Starting fresh.")
                print("\n" + "="*60)
                print(f"🚀 STARTING NEW WORKFLOW (max {self.max_cycles} cycles, {len(self.miner_ids)} concurrent miners)")
                print("="*60)
                current_cycle = 0
            
            # Run remaining cycles
            cycle = current_cycle
            while cycle < self.max_cycles and not self.stop_event.is_set():
                cycle += 1
                is_resume = (self.resume and cycle == current_cycle + 1 and current_cycle > 0)
                should_continue = self._run_single_cycle(cycle, is_resume_cycle=is_resume)
                if not should_continue:
                    break
            
            # Final summary
            print("\n" + "="*60)
            if self.stop_event.is_set():
                print("⏹️ WORKFLOW STOPPED BY USER")
            else:
                print("🎯 WORKFLOW COMPLETED")
            print("="*60)
            print(f"Total cycles: {len(self.cycle_records)}")
            print(f"Miners per cycle: {len(self.miner_ids)}")
            print(f"✅ Workflow log saved to {self.log_path}")
            
            return {
                "success": True,
                "total_cycles": len(self.cycle_records),
                "miner_count": len(self.miner_ids),
                "cycle_records": [asdict(r) for r in self.cycle_records],
                "stopped_by_user": self.stop_event.is_set()
            }
            
        except FileNotFoundError as e:
            print(f"Error: {e}")
            print("\nPlease ensure the session exists in sandbox directory.")
            return {"success": False, "error": str(e)}
        except Exception as e:
            print(f"Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
        finally:
            # Restore signal handler
            self._restore_signal_handler()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run quantitative trading workflow"
    )
    parser.add_argument(
        "session_id",
        type=str,
        help="Session identifier for the workspace"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config.yaml",
        help="Path to configuration YAML file (default: config.yaml)"
    )
    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="Resume from previous workflow state using logs"
    )
    
    return parser.parse_args()


def main():
    """Main entry point for the workflow."""
    args = parse_arguments()
    
    print(f"Starting workflow with:")
    print(f"  Session ID: {args.session_id}")
    print(f"  Config file: {args.config}")
    print(f"  Resume mode: {args.resume}")
    
    launcher = Launcher(
        session_id=args.session_id,
        config_path=args.config,
        resume=args.resume
    )
    result = launcher.run()
    
    if not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()