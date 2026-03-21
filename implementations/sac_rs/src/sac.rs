use base64::{engine::general_purpose::STANDARD, Engine};
use chrono::{DateTime, Utc};
use hmac::{Hmac, Mac};
use pbkdf2::pbkdf2_hmac;
use rand::rngs::OsRng;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::io::Write;
use std::fs;
use std::path::Path;
use uuid::Uuid;

type HmacSha256 = Hmac<Sha256>;

const SUPPORTED_PERMISSION_OPERATIONS: [&str; 2] = ["file.write", "financial.transaction"];
const DEFAULT_KDF_ITERATIONS: u32 = 100_000;

#[derive(Debug)]
pub enum SACError {
    Io(std::io::Error),
    Json(serde_json::Error),
    AgentNotFound,
    AgentAlreadyRevoked,
    PermissionDenied(String),
    InvalidContainer(String),
}

impl From<std::io::Error> for SACError {
    fn from(err: std::io::Error) -> Self {
        SACError::Io(err)
    }
}

impl From<serde_json::Error> for SACError {
    fn from(err: serde_json::Error) -> Self {
        SACError::Json(err)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RootKeyMaterial {
    pub key_id: String,
    pub key_bytes: Vec<u8>,
    pub created_at: DateTime<Utc>,
    pub rotated_at: Option<DateTime<Utc>>,
}

impl RootKeyMaterial {
    pub fn generate() -> Self {
        let mut key_bytes = vec![0u8; 32];
        OsRng.fill_bytes(&mut key_bytes);

        Self {
            key_id: Uuid::new_v4().to_string(),
            key_bytes,
            created_at: Utc::now(),
            rotated_at: None,
        }
    }

    pub fn derive_child_key(&self, purpose: &str) -> Vec<u8> {
        let mut mac =
            HmacSha256::new_from_slice(&self.key_bytes).expect("HMAC can take key of any size");
        mac.update(purpose.as_bytes());
        mac.finalize().into_bytes().to_vec()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryRoot {
    pub memory_id: String,
    pub reference: String,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PermissionCage {
    pub allowed_operations: Vec<String>,
    pub financial_daily_limit: Option<f64>,
    pub financial_single_tx_limit: Option<f64>,
    pub actions_require_confirmation: Vec<String>,
}

impl PermissionCage {
    pub fn default_root() -> Self {
        Self {
            allowed_operations: SUPPORTED_PERMISSION_OPERATIONS
                .iter()
                .map(|op| op.to_string())
                .collect(),
            financial_daily_limit: None,
            financial_single_tx_limit: None,
            actions_require_confirmation: Vec::new(),
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        let mut seen = std::collections::HashSet::new();
        for op in &self.allowed_operations {
            if !seen.insert(op) {
                return Err("allowed_operations must not contain duplicates".to_string());
            }
            if !SUPPORTED_PERMISSION_OPERATIONS.contains(&op.as_str()) {
                return Err(format!("Unsupported operations configured: {}", op));
            }
        }

        for op in &self.actions_require_confirmation {
            if !self.allowed_operations.contains(op) {
                return Err(format!(
                    "actions_require_confirmation must be allowed operations: {}",
                    op
                ));
            }
        }

        if let Some(limit) = self.financial_single_tx_limit {
            if limit < 0.0 {
                return Err("financial_single_tx_limit must be non-negative".to_string());
            }
        }
        if let Some(limit) = self.financial_daily_limit {
            if limit < 0.0 {
                return Err("financial_daily_limit must be non-negative".to_string());
            }
        }
        Ok(())
    }

    pub fn is_subset_of(&self, parent: &PermissionCage) -> bool {
        if !self
            .allowed_operations
            .iter()
            .all(|op| parent.allowed_operations.contains(op))
        {
            return false;
        }

        let financial_ok = if self
            .allowed_operations
            .iter()
            .any(|op| op == "financial.transaction")
        {
            limit_is_subset(self.financial_single_tx_limit, parent.financial_single_tx_limit)
                && limit_is_subset(self.financial_daily_limit, parent.financial_daily_limit)
        } else {
            true
        };

        let required_confirmations: Vec<_> = parent
            .actions_require_confirmation
            .iter()
            .filter(|op| self.allowed_operations.contains(op))
            .collect();

        financial_ok
            && required_confirmations
                .iter()
                .all(|op| self.actions_require_confirmation.contains(*op))
    }

    pub fn check_permission(
        &self,
        operation: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> Result<(), String> {
        self.validate()?;

        if !self.allowed_operations.iter().any(|op| op == operation) {
            return Err(format!("Operation not allowed: {}", operation));
        }
        if !SUPPORTED_PERMISSION_OPERATIONS.contains(&operation) {
            return Err(format!("Unsupported operation: {}", operation));
        }

        if operation == "financial.transaction" {
            let amount = parse_non_negative_f64(context, "amount")?.unwrap_or(0.0);
            let daily_total = parse_non_negative_f64(context, "daily_total")?.unwrap_or(0.0);

            if let Some(limit) = self.financial_single_tx_limit {
                if amount > limit {
                    return Err(format!(
                        "Transaction amount {} exceeds single transaction limit {}",
                        amount, limit
                    ));
                }
            }

            if let Some(daily_limit) = self.financial_daily_limit {
                if daily_total + amount > daily_limit {
                    return Err(format!("Transaction would exceed daily limit {}", daily_limit));
                }
            }
        }

        if self
            .actions_require_confirmation
            .iter()
            .any(|configured| configured == operation)
            && !context
                .get("user_confirmed")
                .or_else(|| context.get("confirmed"))
                .and_then(|v| v.as_bool())
                .unwrap_or(false)
        {
            return Err(format!("Action '{}' requires confirmation", operation));
        }

        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DerivedAgent {
    pub agent_id: String,
    pub purpose: String,
    pub created_at: DateTime<Utc>,
    pub parent_sac_id: String,
    pub derived_key_id: String,
    pub permissions: PermissionCage,
    pub revoked: bool,
    pub revoked_at: Option<DateTime<Utc>>,
}

fn default_version() -> String {
    "1".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SACContainer {
    #[serde(default = "default_version")]
    pub version: String,
    pub sac_id: String,
    pub created_at: DateTime<Utc>,
    pub root_key: RootKeyMaterial,
    pub memory_root: MemoryRoot,
    pub permissions: PermissionCage,
    pub derived_agents: Vec<DerivedAgent>,
    pub recovery_method: Option<String>,
    pub recovery_params: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SerializedRootKeyMaterial {
    key_id: String,
    key_bytes: String,
    created_at: DateTime<Utc>,
    rotated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SerializedMemoryRoot {
    memory_id: String,
    reference: String,
    created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CryptoEnvelope {
    kdf: String,
    iterations: u32,
    salt: String,
    nonce: String,
    mac: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SerializedSACContainer {
    version: String,
    sac_id: String,
    created_at: DateTime<Utc>,
    root_key: SerializedRootKeyMaterial,
    memory_root: SerializedMemoryRoot,
    permissions: PermissionCage,
    derived_agents: Vec<DerivedAgent>,
    recovery_method: Option<String>,
    recovery_params: HashMap<String, serde_json::Value>,
    crypto: CryptoEnvelope,
}

impl SACContainer {
    pub fn create(memory_path: &str) -> Self {
        let root_key = RootKeyMaterial::generate();
        let sac_id = Uuid::new_v4().to_string();
        let now = Utc::now();

        Self {
            version: "1".to_string(),
            sac_id,
            created_at: now,
            root_key,
            memory_root: MemoryRoot {
                memory_id: Uuid::new_v4().to_string(),
                reference: memory_path.to_string(),
                created_at: now,
            },
            permissions: PermissionCage::default_root(),
            derived_agents: Vec::new(),
            recovery_method: None,
            recovery_params: HashMap::new(),
        }
    }

    pub fn validate(&self) -> Result<(), SACError> {
        if self.version != "1" {
            return Err(SACError::InvalidContainer(format!(
                "unsupported version: {}",
                self.version
            )));
        }
        if self.root_key.key_bytes.len() != 32 {
            return Err(SACError::InvalidContainer(
                "root_key.key_bytes must be 32 bytes".to_string(),
            ));
        }
        self.permissions
            .validate()
            .map_err(SACError::InvalidContainer)?;
        for agent in &self.derived_agents {
            agent.permissions
                .validate()
                .map_err(SACError::InvalidContainer)?;
            if !agent.permissions.is_subset_of(&self.permissions) {
                return Err(SACError::InvalidContainer(format!(
                    "derived agent exceeds parent permissions: {}",
                    agent.agent_id
                )));
            }
        }
        Ok(())
    }

    pub fn derive_agent(&mut self, purpose: &str) -> DerivedAgent {
        self.derive_agent_with_permissions(purpose, self.permissions.clone())
            .expect("cloned parent permissions must remain valid")
    }

    pub fn derive_agent_with_permissions(
        &mut self,
        purpose: &str,
        permissions: PermissionCage,
    ) -> Result<DerivedAgent, SACError> {
        permissions
            .validate()
            .map_err(SACError::InvalidContainer)?;
        if !permissions.is_subset_of(&self.permissions) {
            return Err(SACError::InvalidContainer(
                "derived agent permissions cannot exceed parent permissions".to_string(),
            ));
        }

        let child_key = self.root_key.derive_child_key(purpose);
        let agent_id = Uuid::new_v4().to_string();
        let derived_key_id = format!("{:x}", Sha256::digest(&child_key))[..16].to_string();

        let agent = DerivedAgent {
            agent_id,
            purpose: purpose.to_string(),
            created_at: Utc::now(),
            parent_sac_id: self.sac_id.clone(),
            derived_key_id,
            permissions,
            revoked: false,
            revoked_at: None,
        };

        self.derived_agents.push(agent.clone());
        Ok(agent)
    }

    pub fn revoke_agent(&mut self, agent_id: &str) -> Result<(), SACError> {
        let agent = self
            .derived_agents
            .iter_mut()
            .find(|a| a.agent_id == agent_id)
            .ok_or(SACError::AgentNotFound)?;

        if agent.revoked {
            return Err(SACError::AgentAlreadyRevoked);
        }

        agent.revoked = true;
        agent.revoked_at = Some(Utc::now());
        Ok(())
    }

    pub fn check_permission(
        &self,
        operation: &str,
        context: &HashMap<String, serde_json::Value>,
    ) -> Result<(), String> {
        if let Some(agent_id) = context.get("agent_id").and_then(|v| v.as_str()) {
            let agent = self
                .derived_agents
                .iter()
                .find(|a| a.agent_id == agent_id)
                .ok_or_else(|| format!("Unknown derived agent: {}", agent_id))?;
            if agent.revoked {
                return Err(format!("Derived agent revoked: {}", agent_id));
            }
            return agent.permissions.check_permission(operation, context);
        }

        self.permissions.check_permission(operation, context)
    }

    pub fn rotate_key(&mut self) {
        let new_key = RootKeyMaterial::generate();
        self.root_key = new_key;
        self.root_key.rotated_at = Some(Utc::now());
    }

    pub fn export_metadata(&self) -> serde_json::Value {
        json!({
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
                "reference": reference_digest(&self.memory_root.reference),
                "created_at": self.memory_root.created_at,
            },
            "permissions": self.permissions,
            "derived_agents": self.derived_agents,
            "recovery_method": self.recovery_method,
        })
    }

    pub fn save<P: AsRef<Path>>(&self, path: P, passphrase: &str) -> Result<(), SACError> {
        if passphrase.is_empty() {
            return Err(SACError::InvalidContainer("passphrase required".to_string()));
        }
        self.validate()?;

        let mut salt = [0u8; 16];
        let mut nonce = [0u8; 16];
        OsRng.fill_bytes(&mut salt);
        OsRng.fill_bytes(&mut nonce);
        let (enc_key, mac_key) = derive_keys(passphrase, &salt, DEFAULT_KDF_ITERATIONS);

        let mut serialized = SerializedSACContainer {
            version: self.version.clone(),
            sac_id: self.sac_id.clone(),
            created_at: self.created_at,
            root_key: SerializedRootKeyMaterial {
                key_id: self.root_key.key_id.clone(),
                key_bytes: encrypt_field(
                    &enc_key,
                    &nonce,
                    "root_key.key_bytes",
                    &self.root_key.key_bytes,
                ),
                created_at: self.root_key.created_at,
                rotated_at: self.root_key.rotated_at,
            },
            memory_root: SerializedMemoryRoot {
                memory_id: self.memory_root.memory_id.clone(),
                reference: encrypt_field(
                    &enc_key,
                    &nonce,
                    "memory_root.reference",
                    self.memory_root.reference.as_bytes(),
                ),
                created_at: self.memory_root.created_at,
            },
            permissions: self.permissions.clone(),
            derived_agents: self.derived_agents.clone(),
            recovery_method: self.recovery_method.clone(),
            recovery_params: self.recovery_params.clone(),
            crypto: CryptoEnvelope {
                kdf: "pbkdf2-hmac-sha256".to_string(),
                iterations: DEFAULT_KDF_ITERATIONS,
                salt: STANDARD.encode(salt),
                nonce: STANDARD.encode(nonce),
                mac: String::new(),
            },
        };

        serialized.crypto.mac = compute_mac(&serialized, &mac_key)?;

        let json = serde_json::to_string_pretty(&serialized)?;
        atomic_write(path.as_ref(), json.as_bytes())?;
        Ok(())
    }

    pub fn load<P: AsRef<Path>>(path: P, passphrase: &str) -> Result<Self, SACError> {
        if passphrase.is_empty() {
            return Err(SACError::InvalidContainer("passphrase required".to_string()));
        }

        let json = fs::read_to_string(path)?;
        let serialized: SerializedSACContainer = serde_json::from_str(&json)?;

        if serialized.crypto.kdf != "pbkdf2-hmac-sha256" {
            return Err(SACError::InvalidContainer("unsupported KDF".to_string()));
        }

        let salt = STANDARD
            .decode(&serialized.crypto.salt)
            .map_err(|e| SACError::InvalidContainer(format!("invalid salt: {}", e)))?;
        let nonce = STANDARD
            .decode(&serialized.crypto.nonce)
            .map_err(|e| SACError::InvalidContainer(format!("invalid nonce: {}", e)))?;
        let (enc_key, mac_key) = derive_keys(passphrase, &salt, serialized.crypto.iterations);

        let actual_mac = serialized.crypto.mac.clone();
        let expected_mac = compute_mac(&serialized, &mac_key)?;
        if !constant_time_eq(actual_mac.as_bytes(), expected_mac.as_bytes()) {
            return Err(SACError::InvalidContainer(
                "container MAC verification failed".to_string(),
            ));
        }

        let root_key = RootKeyMaterial {
            key_id: serialized.root_key.key_id,
            key_bytes: decrypt_field(
                &enc_key,
                &nonce,
                "root_key.key_bytes",
                &serialized.root_key.key_bytes,
            )?,
            created_at: serialized.root_key.created_at,
            rotated_at: serialized.root_key.rotated_at,
        };
        if root_key.key_bytes.len() != 32 {
            return Err(SACError::InvalidContainer(
                "root_key.key_bytes must decode to 32 bytes".to_string(),
            ));
        }

        let memory_root = MemoryRoot {
            memory_id: serialized.memory_root.memory_id,
            reference: String::from_utf8(decrypt_field(
                &enc_key,
                &nonce,
                "memory_root.reference",
                &serialized.memory_root.reference,
            )?)
            .map_err(|e| SACError::InvalidContainer(format!("invalid memory root: {}", e)))?,
            created_at: serialized.memory_root.created_at,
        };

        let sac = SACContainer {
            version: serialized.version,
            sac_id: serialized.sac_id,
            created_at: serialized.created_at,
            root_key,
            memory_root,
            permissions: serialized.permissions,
            derived_agents: serialized.derived_agents,
            recovery_method: serialized.recovery_method,
            recovery_params: serialized.recovery_params,
        };
        sac.validate()?;
        Ok(sac)
    }
}

fn parse_non_negative_f64(
    context: &HashMap<String, serde_json::Value>,
    key: &str,
) -> Result<Option<f64>, String> {
    let Some(value) = context.get(key) else {
        return Ok(None);
    };
    let number = value
        .as_f64()
        .ok_or_else(|| format!("{} must be numeric", key))?;
    if number < 0.0 {
        return Err(format!("{} must be non-negative", key));
    }
    Ok(Some(number))
}

fn limit_is_subset(child: Option<f64>, parent: Option<f64>) -> bool {
    match (child, parent) {
        (_, None) => true,
        (Some(child), Some(parent)) => child <= parent,
        (None, Some(_)) => false,
    }
}

fn derive_keys(passphrase: &str, salt: &[u8], iterations: u32) -> (Vec<u8>, Vec<u8>) {
    let mut key_material = [0u8; 64];
    pbkdf2_hmac::<Sha256>(passphrase.as_bytes(), salt, iterations, &mut key_material);
    (key_material[..32].to_vec(), key_material[32..].to_vec())
}

fn stream_xor(key: &[u8], nonce: &[u8], label: &str, payload: &[u8]) -> Vec<u8> {
    let mut stream = Vec::with_capacity(payload.len());
    let mut counter = 0u32;
    while stream.len() < payload.len() {
        let mut mac = HmacSha256::new_from_slice(key).expect("HMAC can take key of any size");
        mac.update(nonce);
        mac.update(label.as_bytes());
        mac.update(&counter.to_be_bytes());
        let block = mac.finalize().into_bytes();
        stream.extend_from_slice(&block);
        counter += 1;
    }
    payload
        .iter()
        .zip(stream.iter())
        .map(|(a, b)| a ^ b)
        .collect()
}

fn encrypt_field(key: &[u8], nonce: &[u8], label: &str, payload: &[u8]) -> String {
    STANDARD.encode(stream_xor(key, nonce, label, payload))
}

fn decrypt_field(
    key: &[u8],
    nonce: &[u8],
    label: &str,
    payload: &str,
) -> Result<Vec<u8>, SACError> {
    let decoded = STANDARD
        .decode(payload)
        .map_err(|e| SACError::InvalidContainer(format!("invalid encrypted field: {}", e)))?;
    Ok(stream_xor(key, nonce, label, &decoded))
}

fn compute_mac(serialized: &SerializedSACContainer, mac_key: &[u8]) -> Result<String, SACError> {
    let mut candidate = serde_json::to_value(serialized)?;
    candidate["crypto"]["mac"] = Value::String(String::new());
    let canonical = canonicalize_value(&candidate);
    let payload = serde_json::to_vec(&canonical)?;
    let mut mac = HmacSha256::new_from_slice(mac_key).expect("HMAC can take key of any size");
    mac.update(&payload);
    Ok(hex_string(&mac.finalize().into_bytes()))
}

fn canonicalize_value(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut entries: Vec<_> = map.iter().collect();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            let mut sorted = Map::new();
            for (key, item) in entries {
                sorted.insert(key.clone(), canonicalize_value(item));
            }
            Value::Object(sorted)
        }
        Value::Array(items) => Value::Array(items.iter().map(canonicalize_value).collect()),
        _ => value.clone(),
    }
}

fn hex_string(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{:02x}", byte)).collect()
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right.iter())
        .fold(0u8, |acc, (a, b)| acc | (a ^ b))
        == 0
}

fn reference_digest(reference: &str) -> String {
    let digest = Sha256::digest(reference.as_bytes());
    format!("sha256:{}", hex_string(&digest[..8]))
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), SACError> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;

    let tmp_path = parent.join(format!(
        ".{}.{}.tmp",
        path.file_name().and_then(|name| name.to_str()).unwrap_or("sac"),
        Uuid::new_v4()
    ));

    let write_result = (|| -> Result<(), SACError> {
        let mut file = fs::File::create(&tmp_path)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;

            fs::set_permissions(&tmp_path, fs::Permissions::from_mode(0o600))?;
        }
        fs::rename(&tmp_path, path)?;
        Ok(())
    })();

    if write_result.is_err() {
        let _ = fs::remove_file(&tmp_path);
    }

    write_result
}
