//! Test unified link cost model.

use ulp_atom_kernel::link::{Link, Direction, should_transfer, recompute_cost_kv, recompute_cost_ffn};

#[test]
fn test_datacenter_transfer_kv() {
    let link = Link::datacenter();
    let kv_bytes = 1_000_000;
    let cost = link.transfer_cost(kv_bytes, Direction::Download);
    assert!(cost < 10.0);
}

#[test]
fn test_p2p_keep_kv_local() {
    let link = Link::p2p();
    let kv_bytes = 10_000_000;
    let compute_flops = 1e12;
    let should = should_transfer(kv_bytes, &link, Direction::Download, compute_flops, false);
    assert!(!should);
}

#[test]
fn test_datacenter_large_kv_prefers_transfer() {
    let link = Link::datacenter();
    let large_bytes = 100_000_000;
    let compute_flops = 1e12;
    let should = should_transfer(large_bytes, &link, Direction::Download, compute_flops, false);
    assert!(should);
}

#[test]
fn test_asymmetric_direction_cost() {
    let link = Link::p2p();
    let bytes = 1_000_000;
    let upload = link.transfer_cost(bytes, Direction::Upload);
    let download = link.transfer_cost(bytes, Direction::Download);
    assert!(upload > download);
}

#[test]
fn test_recompute_cost_ffn_higher() {
    let kv_bytes = 1_000_000;
    let compute_flops = 1e12;
    let kv_cost = recompute_cost_kv(kv_bytes, compute_flops);
    let ffn_cost = recompute_cost_ffn(kv_bytes, compute_flops);
    assert!(ffn_cost > kv_cost);
}
