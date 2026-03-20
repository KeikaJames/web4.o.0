use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShardRef {
    pub shard_id: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShardManifest {
    pub model_id: String,
    pub shards: Vec<ShardRef>,
}

#[derive(Debug, Clone)]
pub enum ResolvedShard {
    Local(PathBuf),
    Remote(String),
}

impl ShardManifest {
    pub fn from_json(json: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(json)
    }
}

pub fn resolve_shard(shard: &ShardRef) -> ResolvedShard {
    let path = Path::new(&shard.path);
    if path.exists() {
        ResolvedShard::Local(path.to_path_buf())
    } else if shard.path.starts_with("http://") || shard.path.starts_with("https://") {
        ResolvedShard::Remote(shard.path.clone())
    } else {
        // non-existent local path — still local, caller decides what to do
        ResolvedShard::Local(path.to_path_buf())
    }
}

pub fn load_local_shard(path: &Path) -> Result<Vec<u8>, std::io::Error> {
    std::fs::read(path)
}
