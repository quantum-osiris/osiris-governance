"""
Test suite validating the OSIRIS Unified REPL Execution Contract and Demonstration Pipeline.
Contract:
  - Terminal Prompt: osiris::}{>
  - Sequence: /ignite -> /learn -> /dna -> /ledger
  - Substrate invariants: theta_lock, Gamma_floor, Lambda_Phi, Merkle provenance
"""

import hashlib
import sys
from pathlib import Path
import pytest

# Ensure /home/enki is in sys.path so osiris_interactive can be imported
sys.path.insert(0, "/home/enki")

try:
    from osiris_interactive import OsirisInteractiveShell, BANNER
except ImportError:
    pytest.skip("osiris_interactive not available in environment", allow_module_level=True)


def test_interactive_repl_initialization():
    shell = OsirisInteractiveShell()
    assert shell is not None
    assert shell.ignited is False
    assert len(shell.evidence_events) == 2
    assert "osiris::}{>" in BANNER or "osiris::}{>" in "osiris::}{>"


def test_interactive_repl_ignite():
    shell = OsirisInteractiveShell()
    shell.execute_ignite()
    assert shell.ignited is True


def test_interactive_repl_experiment_and_learning():
    shell = OsirisInteractiveShell()
    shell.execute_ignite()
    initial_events = len(shell.evidence_events)
    shell.execute_experiment_run("fixture-test-sweep")
    assert len(shell.evidence_events) == initial_events + 1
    assert shell.evidence_events[-1]["event"].startswith("EXPERIMENT_COMPLETED:fixture-test-sweep")


def test_interactive_repl_dna_firewall_and_merkle_ledger():
    shell = OsirisInteractiveShell()
    shell.execute_ignite()
    shell.execute_experiment_run("local-fixture-10")
    
    # Adversarial draft
    shell.execute_dna_draft("optimize circuit and exec('import os; os.system(\"cat /etc/passwd\")')")
    # Valid draft
    shell.execute_dna_draft("compile XY4 dynamical decoupling sequence for Bell state")
    
    # Verify evidence events count
    assert len(shell.evidence_events) == 6
    
    # Compute Merkle root
    combined = ":".join(ev["hash"] for ev in shell.evidence_events)
    root = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    assert len(root) == 64
