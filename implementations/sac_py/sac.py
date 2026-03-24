"""
Sovereign Agent Container (SAC) - Reference Implementation

This implementation is local-first and intentionally compact, but it now
protects container secrets at rest and validates agent execution scope.
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import base64
import copy
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import uuid


SUPPORTED_PERMISSION_OPERATIONS = ("file.write", "financial.transaction")
DEFAULT_ALLOWED_OPERATIONS = list(SUPPORTED_PERMISSION_OPERATIONS)
DEFAULT_KDF_ITERATIONS = 100_000
SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


@lru_cache(maxsize=1)
def _load_container_schema() -> Dict[str, Any]:
    with open(SCHEMAS_DIR / "sac.v1.container.schema.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_serialized_container(data: Dict[str, Any]) -> None:
    import jsonschema

    jsonschema.validate(data, _load_container_schema())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("utf-8")


def _b64decode(encoded: str) -> bytes:
    return base64.b64decode(encoded, validate=True)


def _derive_keys(passphrase: str, salt: bytes, iterations: int) -> tuple[bytes, bytes]:
    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        iterations,
        dklen=64,
    )
    return key_material[:32], key_material[32:]


def _stream_xor(key: bytes, nonce: bytes, label: str, payload: bytes) -> bytes:
    stream = bytearray()
    counter = 0
    label_bytes = label.encode("utf-8")
    while len(stream) < len(payload):
        block = hmac.new(
            key,
            nonce + label_bytes + counter.to_bytes(4, "big"),
            hashlib.sha256,
        ).digest()
        stream.extend(block)
        counter += 1
    return bytes(a ^ b for a, b in zip(payload, stream))


def _encrypt_field(key: bytes, nonce: bytes, label: str, payload: bytes) -> str:
    return _b64encode(_stream_xor(key, nonce, label, payload))


def _decrypt_field(key: bytes, nonce: bytes, label: str, payload: str) -> bytes:
    return _stream_xor(key, nonce, label, _b64decode(payload))


def _canonical_container_bytes(data: Dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            tmp_path.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _coerce_non_negative_number(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    numeric_value = float(value)
    if numeric_value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return numeric_value


def _reference_digest(reference: str) -> str:
    digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _limit_is_subset(child: Optional[float], parent: Optional[float]) -> bool:
    if parent is None:
        return True
    if child is None:
        return False
    return child <= parent


@dataclass
class RootKeyMaterial:
    """Root key material for SAC sovereignty."""

    key_id: str
    key_bytes: bytes
    created_at: str
    rotated_at: Optional[str] = None

    @classmethod
    def generate(cls) -> "RootKeyMaterial":
        return cls(
            key_id=str(uuid.uuid4()),
            key_bytes=secrets.token_bytes(32),
            created_at=_utc_now(),
        )

    def derive_child_key(self, purpose: str) -> bytes:
        return hmac.new(
            self.key_bytes,
            purpose.encode("utf-8"),
            hashlib.sha256,
        ).digest()


@dataclass
class MemoryRoot:
    """Reference to the user's local memory root."""

    memory_id: str
    reference: str
    created_at: str

    @classmethod
    def create_local(cls, path: str) -> "MemoryRoot":
        return cls(
            memory_id=str(uuid.uuid4()),
            reference=path,
            created_at=_utc_now(),
        )


@dataclass
class PermissionCage:
    """Permission cage defining what an agent can do."""

    allowed_operations: List[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_OPERATIONS))
    financial_daily_limit: Optional[float] = None
    financial_single_tx_limit: Optional[float] = None
    actions_require_confirmation: List[str] = field(default_factory=list)

    def copy(self) -> "PermissionCage":
        return PermissionCage(
            allowed_operations=list(self.allowed_operations),
            financial_daily_limit=self.financial_daily_limit,
            financial_single_tx_limit=self.financial_single_tx_limit,
            actions_require_confirmation=list(self.actions_require_confirmation),
        )

    def validate(self) -> None:
        if len(set(self.allowed_operations)) != len(self.allowed_operations):
            raise ValueError("allowed_operations must not contain duplicates")
        unsupported = set(self.allowed_operations) - set(SUPPORTED_PERMISSION_OPERATIONS)
        if unsupported:
            raise ValueError(f"Unsupported operations configured: {sorted(unsupported)}")
        unknown_confirmation = set(self.actions_require_confirmation) - set(self.allowed_operations)
        if unknown_confirmation:
            raise ValueError(
                f"actions_require_confirmation must be allowed operations: {sorted(unknown_confirmation)}"
            )
        if self.financial_single_tx_limit is not None:
            _coerce_non_negative_number(self.financial_single_tx_limit, "financial_single_tx_limit")
        if self.financial_daily_limit is not None:
            _coerce_non_negative_number(self.financial_daily_limit, "financial_daily_limit")

    def is_subset_of(self, parent: "PermissionCage") -> bool:
        child_operations = set(self.allowed_operations)
        if not child_operations.issubset(parent.allowed_operations):
            return False

        if "financial.transaction" in child_operations:
            financial_ok = (
                _limit_is_subset(self.financial_single_tx_limit, parent.financial_single_tx_limit)
                and _limit_is_subset(self.financial_daily_limit, parent.financial_daily_limit)
            )
        else:
            financial_ok = True

        required_confirmations = set(parent.actions_require_confirmation).intersection(child_operations)
        return (
            financial_ok
            and required_confirmations.issubset(self.actions_require_confirmation)
        )

    def check_permission(self, operation: str, context: Dict[str, Any]) -> tuple[bool, str]:
        self.validate()

        if operation not in self.allowed_operations:
            return False, f"Operation not allowed: {operation}"
        if operation not in SUPPORTED_PERMISSION_OPERATIONS:
            return False, f"Unsupported operation: {operation}"

        if operation == "financial.transaction":
            try:
                amount = _coerce_non_negative_number(context.get("amount", 0), "amount")
                daily_total = _coerce_non_negative_number(
                    context.get("daily_total", 0), "daily_total"
                )
            except ValueError as exc:
                return False, str(exc)

            if self.financial_single_tx_limit is not None and amount > self.financial_single_tx_limit:
                return False, f"Exceeds single transaction limit: {self.financial_single_tx_limit}"
            if self.financial_daily_limit is not None and daily_total + amount > self.financial_daily_limit:
                return False, f"Exceeds daily limit: {self.financial_daily_limit}"

        # Accept both 'confirmed' (standard) and 'user_confirmed' (legacy) for backward compatibility
        is_confirmed = context.get("confirmed", False) or context.get("user_confirmed", False)
        if operation in self.actions_require_confirmation and not is_confirmed:
            return False, f"Operation requires user confirmation: {operation}"

        return True, "Allowed"


@dataclass
class DerivedAgent:
    """Derived agent with limited scope."""

    agent_id: str
    purpose: str
    created_at: str
    parent_sac_id: str
    derived_key_id: str
    permissions: PermissionCage
    revoked: bool = False
    revoked_at: Optional[str] = None


@dataclass
class SACContainer:
    """Sovereign Agent Container."""

    sac_id: str
    version: str
    created_at: str
    root_key: RootKeyMaterial
    memory_root: MemoryRoot
    permissions: PermissionCage
    derived_agents: List[DerivedAgent] = field(default_factory=list)
    recovery_method: Optional[str] = None
    recovery_params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, memory_path: str = "./memory") -> "SACContainer":
        return cls(
            sac_id=str(uuid.uuid4()),
            version="1",
            created_at=_utc_now(),
            root_key=RootKeyMaterial.generate(),
            memory_root=MemoryRoot.create_local(memory_path),
            permissions=PermissionCage(),
        )

    def validate(self) -> None:
        if self.version != "1":
            raise ValueError(f"Unsupported version: {self.version}")
        if len(self.root_key.key_bytes) != 32:
            raise ValueError("root_key.key_bytes must be 32 bytes")
        self.permissions.validate()
        for agent in self.derived_agents:
            agent.permissions.validate()
            if not agent.permissions.is_subset_of(self.permissions):
                raise ValueError(f"Derived agent exceeds parent permissions: {agent.agent_id}")

    def derive_agent(
        self,
        purpose: str,
        permissions: Optional[PermissionCage] = None,
    ) -> DerivedAgent:
        child_permissions = permissions.copy() if permissions is not None else self.permissions.copy()
        if not child_permissions.is_subset_of(self.permissions):
            raise ValueError("Derived agent permissions cannot exceed parent permissions")

        derived_key = self.root_key.derive_child_key(purpose)
        derived_key_id = hashlib.sha256(derived_key).hexdigest()[:16]

        agent = DerivedAgent(
            agent_id=str(uuid.uuid4()),
            purpose=purpose,
            created_at=_utc_now(),
            parent_sac_id=self.sac_id,
            derived_key_id=derived_key_id,
            permissions=child_permissions,
        )
        self.derived_agents.append(agent)
        return agent

    def get_agent(self, agent_id: str) -> Optional[DerivedAgent]:
        for agent in self.derived_agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def check_permission(self, operation: str, context: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
        context = context or {}
        agent_id = context.get("agent_id")
        if agent_id is None:
            return self.permissions.check_permission(operation, context)

        agent = self.get_agent(agent_id)
        if agent is None:
            return False, f"Unknown derived agent: {agent_id}"
        if agent.revoked:
            return False, f"Derived agent revoked: {agent_id}"
        return agent.permissions.check_permission(operation, context)

    def revoke_agent(self, agent_id: str) -> bool:
        for agent in self.derived_agents:
            if agent.agent_id == agent_id and not agent.revoked:
                agent.revoked = True
                agent.revoked_at = _utc_now()
                return True
        return False

    def rotate_key(self) -> None:
        self.root_key = RootKeyMaterial.generate()
        self.root_key.rotated_at = _utc_now()

    def export_metadata(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "sac_id": self.sac_id,
            "created_at": self.created_at,
            "root_key": {
                "key_id": self.root_key.key_id,
                "created_at": self.root_key.created_at,
                "rotated_at": self.root_key.rotated_at,
            },
            "memory_root": {
                "memory_id": self.memory_root.memory_id,
                "reference": _reference_digest(self.memory_root.reference),
                "created_at": self.memory_root.created_at,
            },
            "permissions": asdict(self.permissions),
            "derived_agents": [asdict(agent) for agent in self.derived_agents],
            "recovery_method": self.recovery_method,
        }

    def _encrypted_container_data(self, passphrase: str) -> Dict[str, Any]:
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(16)
        enc_key, mac_key = _derive_keys(passphrase, salt, DEFAULT_KDF_ITERATIONS)

        data = {
            "version": self.version,
            "sac_id": self.sac_id,
            "created_at": self.created_at,
            "root_key": {
                "key_id": self.root_key.key_id,
                "key_bytes": _encrypt_field(enc_key, nonce, "root_key.key_bytes", self.root_key.key_bytes),
                "created_at": self.root_key.created_at,
                "rotated_at": self.root_key.rotated_at,
            },
            "memory_root": {
                "memory_id": self.memory_root.memory_id,
                "reference": _encrypt_field(
                    enc_key,
                    nonce,
                    "memory_root.reference",
                    self.memory_root.reference.encode("utf-8"),
                ),
                "created_at": self.memory_root.created_at,
            },
            "permissions": asdict(self.permissions),
            "derived_agents": [asdict(agent) for agent in self.derived_agents],
            "recovery_method": self.recovery_method,
            "recovery_params": copy.deepcopy(self.recovery_params),
            "crypto": {
                "kdf": "pbkdf2-hmac-sha256",
                "iterations": DEFAULT_KDF_ITERATIONS,
                "salt": _b64encode(salt),
                "nonce": _b64encode(nonce),
                "mac": "",
            },
        }
        mac = hmac.new(mac_key, _canonical_container_bytes(data), hashlib.sha256).hexdigest()
        data["crypto"]["mac"] = mac
        return data

    def save(self, path: Path, passphrase: str) -> None:
        if not passphrase:
            raise ValueError("passphrase required")
        self.validate()
        data = self._encrypted_container_data(passphrase)
        _validate_serialized_container(data)
        _atomic_write_json(path, data)

    @classmethod
    def load(cls, path: Path, passphrase: str) -> "SACContainer":
        if not passphrase:
            raise ValueError("passphrase required")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _validate_serialized_container(data)

        crypto = data["crypto"]
        salt = _b64decode(crypto["salt"])
        nonce = _b64decode(crypto["nonce"])
        enc_key, mac_key = _derive_keys(passphrase, salt, crypto["iterations"])

        candidate = copy.deepcopy(data)
        actual_mac = candidate["crypto"]["mac"]
        candidate["crypto"]["mac"] = ""
        expected_mac = hmac.new(
            mac_key,
            _canonical_container_bytes(candidate),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(actual_mac, expected_mac):
            raise ValueError("container MAC verification failed")

        root_key = RootKeyMaterial(
            key_id=data["root_key"]["key_id"],
            key_bytes=_decrypt_field(enc_key, nonce, "root_key.key_bytes", data["root_key"]["key_bytes"]),
            created_at=data["root_key"]["created_at"],
            rotated_at=data["root_key"].get("rotated_at"),
        )
        if len(root_key.key_bytes) != 32:
            raise ValueError("root_key.key_bytes must decode to 32 bytes")

        memory_root = MemoryRoot(
            memory_id=data["memory_root"]["memory_id"],
            reference=_decrypt_field(
                enc_key,
                nonce,
                "memory_root.reference",
                data["memory_root"]["reference"],
            ).decode("utf-8"),
            created_at=data["memory_root"]["created_at"],
        )
        permissions = PermissionCage(**data["permissions"])
        derived_agents = [
            DerivedAgent(
                agent_id=agent["agent_id"],
                purpose=agent["purpose"],
                created_at=agent["created_at"],
                parent_sac_id=agent["parent_sac_id"],
                derived_key_id=agent["derived_key_id"],
                permissions=PermissionCage(**agent["permissions"]),
                revoked=agent["revoked"],
                revoked_at=agent.get("revoked_at"),
            )
            for agent in data["derived_agents"]
        ]

        sac = cls(
            sac_id=data["sac_id"],
            version=data["version"],
            created_at=data["created_at"],
            root_key=root_key,
            memory_root=memory_root,
            permissions=permissions,
            derived_agents=derived_agents,
            recovery_method=data.get("recovery_method"),
            recovery_params=data.get("recovery_params", {}),
        )
        sac.validate()
        return sac

    def init_chronara(self):
        """Initialize Chronara context for adapter evolution."""
        from implementations.sac_py.chronara_nexus import Collector, Governor, AdapterRef, AdapterMode
        initial_adapter = AdapterRef("default", 1, AdapterMode.SERVE)
        self._chronara_collector = Collector(initial_adapter)
        self._chronara_governor = Governor(initial_adapter)

    def record_observation(self, observation: dict):
        """Record observation through Chronara admission gate."""
        if not hasattr(self, '_chronara_collector'):
            self.init_chronara()
        if hasattr(self, '_chronara_governor'):
            self._chronara_collector.set_active_adapter(self._chronara_governor.active_adapter)
        return self._chronara_collector.admit_observation(observation)

    def current_adapter_ref(self):
        """Get current active adapter reference.

        Returns the serve adapter (stable specialization).
        For full specialization-aware selection, use current_adapter_selection().
        """
        if not hasattr(self, '_chronara_collector'):
            self.init_chronara()
        if hasattr(self, '_chronara_governor'):
            selection = self._chronara_governor.get_adapter_selection()
            self._chronara_collector.set_active_adapter(selection.get_serve_adapter())
            return selection.get_serve_adapter()
        return self._chronara_collector.get_active_adapter()

    def current_adapter_selection(self):
        """Get specialization-aware adapter selection.

        Returns AdapterSelection with stable, shared, and candidate adapters.
        Serve path uses stable + optional shared augmentation.
        Candidate remains isolated until promoted.
        """
        if not hasattr(self, '_chronara_governor'):
            self.init_chronara()
        return self._chronara_governor.get_adapter_selection()

    def fallback_to_stable(self) -> bool:
        """Fallback to stable adapter on specialization failure.

        Clears candidate, resets to stable serve path.
        Preserves shared adapter if exists.
        """
        if not hasattr(self, '_chronara_governor'):
            self.init_chronara()
        self._chronara_governor.rollback_to_stable()
        if hasattr(self, '_chronara_collector'):
            self._chronara_collector.set_active_adapter(self._chronara_governor.active_adapter)
        return True

    def promote_candidate_if_valid(self, candidate):
        """Promote candidate adapter if validation passes."""
        if not hasattr(self, '_chronara_governor'):
            self.init_chronara()
        promoted = self._chronara_governor.promote_candidate(candidate)
        if promoted and hasattr(self, '_chronara_collector'):
            self._chronara_collector.set_active_adapter(self._chronara_governor.active_adapter)
        return promoted

    def create_shadow_eval_request(self, candidate, input_data: bytes):
        """Create shadow eval request for candidate validation."""
        if not hasattr(self, '_chronara_governor'):
            self.init_chronara()
        return self._chronara_governor.create_shadow_request(candidate, input_data)

    def validate_from_atom_result(self, candidate, atom_result: dict):
        """Validate candidate using atom execution result."""
        if not hasattr(self, '_chronara_governor'):
            self.init_chronara()
        return self._chronara_governor.validate_from_atom_result(candidate, atom_result)

    def validate_from_comparison(self, candidate, comparison_result: dict):
        """Validate candidate using shadow comparison result."""
        if not hasattr(self, '_chronara_governor'):
            self.init_chronara()
        return self._chronara_governor.validate_from_comparison(candidate, comparison_result)

    def extract_federation_summary(self, source_node: Optional[str] = None):
        """Extract federation-ready summary from all Chronara layers.

        Phase 10: Unified extraction from Governor, Collector, and Consolidator.
        Safe to call during serve path - never blocks or raises.

        Returns:
            FederationSummary: Structured summary for cross-node exchange
        """
        try:
            # Initialize if needed
            if not hasattr(self, '_chronara_governor'):
                self.init_chronara()

            # Get consolidator params if available
            consolidator_params = None
            if hasattr(self, '_chronara_consolidator'):
                consolidator = self._chronara_consolidator
                # Use candidate params if available, else stable
                if consolidator.candidate_adapter:
                    consolidator_params = consolidator.get_specialization_params(AdapterSpecialization.CANDIDATE)
                elif consolidator.stable_adapter:
                    consolidator_params = consolidator.get_specialization_params(AdapterSpecialization.STABLE)

            # Extract from Governor (primary source)
            summary = self._chronara_governor.extract_federation_summary(
                consolidator_params=consolidator_params,
                source_node=source_node,
            )

            return summary

        except Exception:
            # Failure safety: return minimal summary
            from chronara_nexus.types import FederationSummary
            return FederationSummary._minimal_safe_summary(
                adapter_id=getattr(self, 'sac_id', 'unknown'),
                generation=0,
                source_node=source_node,
            )

    def extract_chronara_full_summary(self) -> dict:
        """Extract full layered summary from all Chronara components.

        Phase 10: Combined summary from Governor, Collector, and Consolidator
        for internal diagnostics and federation preparation.

        Returns:
            dict: Combined summary from all layers
        """
        result = {
            "federation_summary": None,
            "observation_summary": None,
            "parameter_summary": None,
            "governor_traces": [],
        }

        try:
            # Federation summary from Governor
            if hasattr(self, '_chronara_governor'):
                summary = self.extract_federation_summary()
                if summary:
                    result["federation_summary"] = summary.to_dict()
                    # Also include validation traces
                    traces = self._chronara_governor.get_validation_traces()
                    result["governor_traces"] = [t.to_dict() for t in traces]

            # Observation summary from Collector
            if hasattr(self, '_chronara_collector'):
                result["observation_summary"] = self._chronara_collector.extract_observation_summary()

            # Parameter summary from Consolidator
            if hasattr(self, '_chronara_consolidator'):
                result["parameter_summary"] = self._chronara_consolidator.extract_parameter_summary()

        except Exception:
            # Failure safety: return what we have
            pass

        return result

    def check_exchange_compatibility(
        self,
        remote_summary_dict: dict,
    ) -> dict:
        """Check compatibility with remote federation summary.

        Phase 11: Exchange gate entry point for SAC.
        Accepts remote summary as dict (imported from network/storage).
        Safe to call during serve path - never blocks or raises.

        Args:
            remote_summary_dict: Remote federation summary as dictionary

        Returns:
            dict: Exchange gate result as dictionary
        """
        from chronara_nexus.types import FederationSummary, FederationExchangeGate

        try:
            # Parse remote summary
            remote_summary = FederationSummary.from_dict(remote_summary_dict)

            # Initialize if needed
            if not hasattr(self, '_chronara_governor'):
                self.init_chronara()

            # Get consolidator params if available
            consolidator_params = None
            if hasattr(self, '_chronara_consolidator'):
                consolidator = self._chronara_consolidator
                if consolidator.candidate_adapter:
                    consolidator_params = consolidator.get_specialization_params(AdapterSpecialization.CANDIDATE)
                elif consolidator.stable_adapter:
                    consolidator_params = consolidator.get_specialization_params(AdapterSpecialization.STABLE)

            # Use Governor's exchange compatibility check
            gate = self._chronara_governor.check_exchange_compatibility(
                remote_summary=remote_summary,
                local_params=consolidator_params,
            )

            # Incorporate into traces
            self._chronara_governor.incorporate_exchange_gate(gate)

            return gate.to_dict()

        except Exception:
            # Failure safety: return reject gate
            from chronara_nexus.types import (
                FederationExchangeGate,
                ExchangeStatus,
                LineageCompatibility,
                SpecializationCompatibility,
                ValidationCompatibility,
                ComparisonCompatibility,
            )
            from datetime import datetime

            gate = FederationExchangeGate(
                local_adapter_id=getattr(self, 'sac_id', 'unknown'),
                local_generation=0,
                remote_adapter_id=remote_summary_dict.get('identity', {}).get('adapter_id', 'unknown'),
                remote_generation=remote_summary_dict.get('identity', {}).get('generation', 0),
                lineage=LineageCompatibility(
                    compatible=False,
                    match_score=0.0,
                    generation_gap=0,
                    is_parent_child=False,
                    lineage_hash_match=False,
                    reason="parse_error",
                ),
                specialization=SpecializationCompatibility(
                    compatible=False,
                    local_spec="unknown",
                    remote_spec=remote_summary_dict.get('identity', {}).get('specialization', 'unknown'),
                    can_compose=False,
                    reason="parse_error",
                ),
                validation=ValidationCompatibility(
                    acceptable=False,
                    local_score=0.0,
                    remote_score=0.0,
                    score_delta=0.0,
                    meets_threshold=False,
                    reason="parse_error",
                ),
                comparison=ComparisonCompatibility(
                    acceptable=False,
                    local_status="unknown",
                    remote_status=remote_summary_dict.get('comparison_outcome', {}).get('status', 'unknown'),
                    both_acceptable=False,
                    reason="parse_error",
                ),
                status=ExchangeStatus.REJECT,
                recommendation="reject_parse_error",
                reason="Error parsing remote summary",
                fallback_used=True,
                version="1.1",
                timestamp=datetime.utcnow().isoformat() + "Z",
            )
            return gate.to_dict()

    def can_accept_remote_summary(self, remote_summary_dict: dict) -> bool:
        """Quick check if remote summary can be accepted.

        Phase 11: Fast path for simple accept/reject decisions.
        """
        from chronara_nexus.types import FederationSummary

        try:
            remote_summary = FederationSummary.from_dict(remote_summary_dict)

            if not hasattr(self, '_chronara_governor'):
                self.init_chronara()

            return self._chronara_governor.can_accept_remote_summary(remote_summary)
        except Exception:
            return False
