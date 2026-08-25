import 'package:flutter/material.dart' show IconData, Icons;

/// Redeemable reward catalog. Costs are in EcoPoints; redemption deducts
/// from the user's balance (later: POST /rewards/redeem on the backend).
class RewardOption {
  const RewardOption(this.id, this.label, this.partner, this.cost, this.icon);
  final String id;
  final String label;
  final String partner;
  final int cost;
  final IconData icon;
}

const rewardCatalog = <RewardOption>[
  RewardOption(
    'eco_store_20',
    '20% Off',
    'Eco Store',
    500,
    Icons.card_giftcard,
  ),
  RewardOption(
    'greenmart_5',
    '\$5 Coupon',
    'GreenMart',
    800,
    Icons.account_balance_wallet,
  ),
  RewardOption(
    'free_collection',
    'Free Collection',
    'Next Order',
    1000,
    Icons.inventory_2,
  ),
];
