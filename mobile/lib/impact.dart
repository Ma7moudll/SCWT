import 'models.dart';

/// Environmental-impact conversion layer.
///
/// All factors live HERE so they can be tuned (or replaced by backend
/// values) without touching any UI. Factors are widely used public
/// estimates per kg of recycled material; UI must label results as
/// estimates.
class ImpactFactors {
  const ImpactFactors({
    this.co2KgPerKg = 2.5,
    this.treesPerKg = 0.017,
    this.energyKwhPerKg = 4.0,
    this.waterLitersPerKg = 13.0,
  });

  final double co2KgPerKg;
  final double treesPerKg;
  final double energyKwhPerKg;
  final double waterLitersPerKg;
}

/// Estimated market value per kg of recovered material, in EGP.
/// NOT final — will come from backend/admin configuration later.
const Map<String, double> materialValueEgpPerKg = {
  'plastic': 12.0,
  'metal': 45.0,
  'paper': 4.0,
  'other': 2.0,
};

class MaterialTotal {
  const MaterialTotal(this.material, this.weightKg);
  final String material; // display name, e.g. 'Plastic'
  final double weightKg;

  String get display => '${weightKg.toStringAsFixed(1)} kg';
}

class ImpactSummary {
  const ImpactSummary({
    required this.totalWeightKg,
    required this.depositCount,
    required this.pointsEarned,
    required this.weekPoints,
    required this.monthWeightKg,
    required this.byMaterial,
    required this.factors,
  });

  final double totalWeightKg;
  final int depositCount;
  final int pointsEarned;

  /// EcoPoints earned in the last 7 days.
  final int weekPoints;

  /// Weight deposited in the current calendar month.
  final double monthWeightKg;

  /// Per-material totals, largest first.
  final List<MaterialTotal> byMaterial;
  final ImpactFactors factors;

  double get co2Kg => totalWeightKg * factors.co2KgPerKg;
  double get trees => totalWeightKg * factors.treesPerKg;
  double get energyKwh => totalWeightKg * factors.energyKwhPerKg;
  double get waterLiters => totalWeightKg * factors.waterLitersPerKg;

  int get estimatedValueEgp {
    var v = 0.0;
    for (final m in byMaterial) {
      v +=
          m.weightKg * (materialValueEgpPerKg[m.material.toLowerCase()] ?? 2.0);
    }
    return v.round();
  }
}

String _displayCase(String key) =>
    key.isEmpty ? key : key[0].toUpperCase() + key.substring(1);

/// Derives every impact number from REAL user activity (verified deposits).
class ImpactCalculator {
  static ImpactSummary summarize(
    List<Contribution> contributions, {
    ImpactFactors factors = const ImpactFactors(),
    DateTime? now,
  }) {
    final at = now ?? DateTime.now();
    final weekAgo = at.subtract(const Duration(days: 7));
    final totals = <String, double>{};
    var totalG = 0.0;
    var points = 0;
    var weekPoints = 0;
    var monthG = 0.0;

    for (final c in contributions) {
      totalG += c.weight;
      points += c.points;
      if (c.timestamp.isAfter(weekAgo)) weekPoints += c.points;
      if (c.timestamp.year == at.year && c.timestamp.month == at.month) {
        monthG += c.weight;
      }
      final key = c.materialType.toLowerCase();
      totals[key] = (totals[key] ?? 0) + c.weight;
    }

    final byMaterial =
        totals.entries
            .map((e) => MaterialTotal(_displayCase(e.key), e.value / 1000))
            .toList()
          ..sort((a, b) => b.weightKg.compareTo(a.weightKg));

    return ImpactSummary(
      totalWeightKg: totalG / 1000,
      depositCount: contributions.length,
      pointsEarned: points,
      weekPoints: weekPoints,
      monthWeightKg: monthG / 1000,
      byMaterial: byMaterial,
      factors: factors,
    );
  }
}
