import 'package:flutter/material.dart' show IconData, Icons;

import 'models.dart';

/// Deterministic badge definitions. A badge is unlocked purely by evaluating
/// its [criteria] against the user's verified deposit history — no decorative
/// or manually toggled badges.
class BadgeDef {
  const BadgeDef(
    this.id,
    this.title,
    this.description,
    this.icon,
    this.criteria,
  );
  final String id;
  final String title;
  final String description;
  final IconData icon;
  final bool Function(BadgeStats stats) criteria;
}

class BadgeStats {
  const BadgeStats({
    required this.depositCount,
    required this.totalWeightKg,
    required this.points,
  });
  final int depositCount;
  final double totalWeightKg; // kilograms
  final int points;

  static BadgeStats from(List<Contribution> contributions) {
    var g = 0.0;
    var pts = 0;
    for (final c in contributions) {
      g += c.weight;
      pts += c.points;
    }
    return BadgeStats(
      depositCount: contributions.length,
      totalWeightKg: g / 1000,
      points: pts,
    );
  }
}

final badgeCatalog = <BadgeDef>[
  BadgeDef(
    'first_recycle',
    'First Recycle',
    'Complete your first verified deposit',
    Icons.recycling,
    (s) => s.depositCount >= 1,
  ),
  BadgeDef(
    'ten_kg',
    '10 kg Recycled',
    'Recycle 10 kg of material in total',
    Icons.inventory_2,
    (s) => s.totalWeightKg >= 10,
  ),
  BadgeDef(
    'eco_warrior',
    'Eco Warrior',
    'Complete 25 verified deposits',
    Icons.eco,
    (s) => s.depositCount >= 25,
  ),
  BadgeDef(
    'green_champion',
    'Green Champion',
    'Earn 500 EcoPoints in total',
    Icons.emoji_events,
    (s) => s.points >= 500,
  ),
];

/// Evaluates the catalog against the user's real activity.
Map<String, bool> evaluateBadges(List<Contribution> contributions) {
  final stats = BadgeStats.from(contributions);
  return {for (final b in badgeCatalog) b.id: b.criteria(stats)};
}
