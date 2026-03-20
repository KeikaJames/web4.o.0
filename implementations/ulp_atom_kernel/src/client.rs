use crate::kernel::{AtomRequest, AtomResponse};
use std::time::Duration;

pub struct RemoteClient {
    client: reqwest::Client,
}

impl RemoteClient {
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::builder()
                .timeout(Duration::from_secs(30))
                .build()
                .expect("failed to build http client"),
        }
    }

    pub async fn dispatch(&self, url: &str, request: AtomRequest) -> Result<AtomResponse, String> {
        let response = self.client
            .post(url)
            .json(&request)
            .send()
            .await
            .map_err(|e| format!("send: {e}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(format!("server error {status}: {body}"));
        }

        response
            .json::<AtomResponse>()
            .await
            .map_err(|e| format!("parse response: {e}"))
    }
}

impl Default for RemoteClient {
    fn default() -> Self {
        Self::new()
    }
}

pub async fn dispatch_remote(url: &str, request: AtomRequest) -> Result<AtomResponse, String> {
    RemoteClient::new().dispatch(url, request).await
}
