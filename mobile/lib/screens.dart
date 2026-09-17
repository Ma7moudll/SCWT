import 'dart:math' show max;

import 'package:flutter/material.dart';

import 'api/app_config.dart';
import 'api/api_client.dart';
import 'api/backend_gateway.dart';
import 'api/contract.dart' show BackendReward, rewardIcon;
import 'app_flow_nav.dart';
import 'badges.dart';
import 'impact.dart';
import 'models.dart';
import 'repositories.dart';
import 'rewards.dart';
import 'store.dart';
import 'theme.dart';

const navItems = [
  (Screen.home, 'Home', Icons.eco, Icons.eco_outlined),
  (Screen.history, 'History', Icons.receipt_long, Icons.receipt_long_outlined),
  (Screen.rewards, 'Rewards', Icons.emoji_events, Icons.emoji_events_outlined),
  (Screen.profile, 'Profile', Icons.person, Icons.person_outline),
];

// ---------------------------------------------------------------------------
// Shared small widgets
// ---------------------------------------------------------------------------

class LeafMark extends StatelessWidget {
  const LeafMark({super.key, this.small = false, this.color});
  final bool small;
  final Color? color;
  @override
  Widget build(BuildContext context) {
    final s = small ? 27.0 : 48.0;
    final icon = small ? 17.0 : 28.0;
    return Container(
      width: s,
      height: s,
      decoration: const BoxDecoration(
        color: AppColors.lightGreenBg,
        shape: BoxShape.circle,
      ),
      child: Icon(Icons.eco, size: icon, color: color ?? AppColors.primary),
    );
  }
}

class ScreenHeader extends StatelessWidget {
  const ScreenHeader({
    super.key,
    this.title,
    this.back = false,
    required this.go,
  });
  final String? title;
  final bool back;
  final Go go;
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        if (back)
          IconButton(
            icon: const Icon(Icons.arrow_back_ios_new, size: 20),
            onPressed: () => go(Screen.home),
          )
        else if (title == null)
          const LeafMark(small: true)
        else
          const SizedBox(width: 20),
        Expanded(
          child: title != null
              ? Text(
                  title!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                  ),
                )
              : Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: const [
                    LeafMark(small: true, color: AppColors.darkGreen),
                    SizedBox(width: 8),
                    Text(
                      'SCWT',
                      style: TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 17,
                      ),
                    ),
                  ],
                ),
        ),
        IconButton(
          icon: const Icon(Icons.settings_outlined, size: 20),
          onPressed: () => _warn(context, 'Settings are coming soon.'),
        ),
      ],
    );
  }
}

void _warn(BuildContext context, String msg) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(msg, style: const TextStyle(fontSize: 12)),
      behavior: SnackBarBehavior.floating,
    ),
  );
}

class PrimaryButton extends StatelessWidget {
  const PrimaryButton({super.key, required this.label, this.icon, this.onTap});
  final String label;
  final IconData? icon;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.primary,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
          elevation: 4,
          shadowColor: AppColors.primary.withValues(alpha: 0.17),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 17),
              const SizedBox(width: 8),
            ],
            Text(
              label,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w800),
            ),
          ],
        ),
      ),
    );
  }
}

void showToast(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Row(
        children: [
          const Icon(Icons.check_circle, color: Color(0xFF52d67d), size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(fontSize: 12, color: Colors.white),
            ),
          ),
        ],
      ),
      backgroundColor: AppColors.foreground,
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
    ),
  );
}

void showToastError(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Row(
        children: [
          const Icon(Icons.error_outline, color: AppColors.notice, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(fontSize: 12, color: Colors.white),
            ),
          ),
        ],
      ),
      backgroundColor: AppColors.foreground,
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
    ),
  );
}

class SectionHeading extends StatelessWidget {
  const SectionHeading(this.text, {super.key});
  final String text;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Text(
        text,
        style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Splash
// ---------------------------------------------------------------------------

class Splash extends StatelessWidget {
  const Splash({super.key, required this.onStart});
  final VoidCallback onStart;
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [
              AppColors.splashTop,
              AppColors.splashMid,
              AppColors.splashBottom,
            ],
          ),
        ),
        child: Stack(
          children: [
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              height: 170,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [0.48, 0.72, 0.35, 0.9, 0.6].map((h) {
                  return Container(
                    width: 40,
                    height: 170 * h,
                    decoration: const BoxDecoration(
                      color: Color(0xFF003a2d),
                      borderRadius: BorderRadius.vertical(
                        top: Radius.circular(4),
                      ),
                    ),
                  );
                }).toList(),
              ),
            ),
            Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Transform.rotate(
                    angle: -0.14,
                    child: Container(
                      width: 92,
                      height: 92,
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.white, width: 5),
                        borderRadius: BorderRadius.only(
                          topLeft: Radius.circular(30),
                          bottomRight: Radius.circular(30),
                          topRight: Radius.circular(8),
                          bottomLeft: Radius.circular(8),
                        ),
                      ),
                      child: Center(
                        child: Transform.rotate(
                          angle: 0.14,
                          child: const Icon(
                            Icons.eco,
                            size: 54,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                  const Text(
                    'SCWT',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 38,
                      letterSpacing: -1.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 7),
                  Text(
                    'Smart Campus Waste Transformation',
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.88),
                      fontSize: 14,
                    ),
                  ),
                ],
              ),
            ),
            Positioned(
              left: 25,
              right: 25,
              bottom: 120,
              child: const Text(
                'Together we can\nbuild a greener future',
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  height: 1.45,
                ),
              ),
            ),
            Positioned(
              left: 25,
              right: 25,
              bottom: 45,
              child: SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: onStart,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.primary,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 15),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(999),
                    ),
                    elevation: 4,
                    shadowColor: const Color(0x55003d2b),
                  ),
                  child: const Text(
                    'Get Started',
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

class AuthShell extends StatelessWidget {
  const AuthShell({
    super.key,
    required this.title,
    required this.subtitle,
    required this.onBack,
    required this.child,
  });
  final String title;
  final String subtitle;
  final VoidCallback onBack;
  final Widget child;
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Colors.white, Color(0xFFeef8f2), Color(0xFFe4f1e9)],
          ),
        ),
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
            child: Container(
              constraints: const BoxConstraints(maxWidth: 430),
              padding: const EdgeInsets.fromLTRB(26, 20, 26, 32),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: const Color(0xFFd8e7df)),
                borderRadius: BorderRadius.circular(30),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x1f1b5b3a),
                    blurRadius: 60,
                    offset: Offset(0, 24),
                  ),
                ],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      IconButton(
                        icon: const Icon(Icons.arrow_back_ios_new, size: 20),
                        onPressed: onBack,
                      ),
                      Expanded(
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: const [
                            LeafMark(small: true, color: AppColors.darkGreen),
                            SizedBox(width: 8),
                            Text(
                              'SCWT',
                              style: TextStyle(
                                color: AppColors.darkGreen,
                                fontSize: 18,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  Text(
                    title,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 28,
                      letterSpacing: -0.8,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 9),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 28),
                    child: Text(
                      subtitle,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: AppColors.mutedForeground,
                        fontSize: 13,
                        height: 1.5,
                      ),
                    ),
                  ),
                  child,
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class AuthTextField extends StatefulWidget {
  const AuthTextField({
    super.key,
    required this.label,
    required this.hint,
    this.controller,
    this.obscure = false,
    this.keyboardType,
  });
  final String label;
  final String hint;
  final TextEditingController? controller;
  final bool obscure;
  final TextInputType? keyboardType;
  @override
  State<AuthTextField> createState() => _AuthTextFieldState();
}

class _AuthTextFieldState extends State<AuthTextField> {
  late bool _visible = !widget.obscure;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.label,
          style: const TextStyle(
            color: Color(0xFF52635b),
            fontSize: 12,
            fontWeight: FontWeight.w700,
          ),
        ),
        const SizedBox(height: 7),
        TextField(
          controller: widget.controller,
          obscureText: widget.obscure && !_visible,
          keyboardType: widget.keyboardType,
          autocorrect: false,
          style: const TextStyle(fontSize: 13, color: AppColors.foreground),
          decoration: InputDecoration(
            hintText: widget.hint,
            hintStyle: const TextStyle(color: Color(0xFFB9C6BF), fontSize: 13),
            filled: true,
            fillColor: Colors.white,
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 13,
              vertical: 13,
            ),
            suffixIcon: widget.obscure
                ? IconButton(
                    icon: Icon(
                      _visible
                          ? Icons.visibility_off_outlined
                          : Icons.visibility_outlined,
                      size: 18,
                      color: const Color(0xFF9aa9a2),
                    ),
                    onPressed: () => setState(() => _visible = !_visible),
                  )
                : null,
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: AppColors.border),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(
                color: AppColors.primary,
                width: 1.5,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class Login extends StatefulWidget {
  const Login({
    super.key,
    required this.onBack,
    required this.onSignup,
    required this.onSuccess,
  });
  final VoidCallback onBack;
  final VoidCallback onSignup;
  final VoidCallback onSuccess;
  @override
  State<Login> createState() => _LoginState();
}

class _LoginState extends State<Login> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  String _error = '';
  bool _busy = false;

  Future<void> _submit() async {
    final email = _email.text.trim();
    final validEmail =
        email.isNotEmpty && email.contains('@') && email.contains('.');
    if (!validEmail || _password.text.isEmpty) {
      setState(() => _error = 'Enter a valid email and password.');
      return;
    }
    setState(() {
      _error = '';
      _busy = true;
    });
    try {
      if (AppConfig.isProduction) {
        // Real backend authentication (SCWT Backend (FastAPI)).
        await BackendGateway.instance.login(
          email: email,
          password: _password.text,
        );
        await BackendGateway.instance.syncFromBackend();
      } else {
        // Demo mode: local session only.
        await AppStore.instance.login(email: email);
      }
      if (mounted) widget.onSuccess();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Something went wrong. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AuthShell(
      title: 'Welcome back',
      subtitle:
          'Sign in with your campus email to continue your recycling journey.',
      onBack: widget.onBack,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          AuthTextField(
            label: 'Email',
            hint: 'e.g. emma@campus.edu',
            controller: _email,
            keyboardType: TextInputType.emailAddress,
          ),
          const SizedBox(height: 16),
          AuthTextField(
            label: 'Password',
            hint: 'Enter your password',
            controller: _password,
            obscure: true,
          ),
          if (_error.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              _error,
              style: const TextStyle(
                color: AppColors.red,
                fontSize: 12,
                height: 1.4,
              ),
            ),
          ],
          const SizedBox(height: 8),
          PrimaryButton(
            label: _busy ? 'Signing in…' : 'Login',
            onTap: _busy ? null : _submit,
          ),
          const SizedBox(height: 14),
          Center(
            child: GestureDetector(
              onTap: () => showToast(context, 'Password reset is coming soon.'),
              child: const Text(
                'Forgot password?',
                style: TextStyle(
                  color: AppColors.mutedForeground,
                  fontSize: 12,
                  decoration: TextDecoration.underline,
                ),
              ),
            ),
          ),
          const SizedBox(height: 14),
          Wrap(
            alignment: WrapAlignment.center,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              const Text(
                'New to SCWT? ',
                style: TextStyle(
                  color: AppColors.mutedForeground,
                  fontSize: 12,
                ),
              ),
              GestureDetector(
                onTap: widget.onSignup,
                child: const Text(
                  'Create an account',
                  style: TextStyle(
                    color: AppColors.darkGreen,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    decoration: TextDecoration.underline,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class Signup extends StatefulWidget {
  const Signup({
    super.key,
    required this.onBack,
    required this.onLogin,
    required this.onSuccess,
  });
  final VoidCallback onBack;
  final VoidCallback onLogin;
  final VoidCallback onSuccess;
  @override
  State<Signup> createState() => _SignupState();
}

class _SignupState extends State<Signup> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _id = TextEditingController();
  final _phone = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  String _error = '';
  bool _busy = false;

  Future<void> _submit() async {
    final email = _email.text.trim();
    final validEmail =
        email.isNotEmpty && email.contains('@') && email.contains('.');
    final digits = _phone.text.replaceAll(RegExp(r'\D'), '');
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Please enter your full name.');
      return;
    }
    if (!validEmail) {
      setState(() => _error = 'Enter a valid email address.');
      return;
    }
    if (_id.text.trim().length < 4 || digits.length < 8) {
      setState(
        () => _error =
            'Student ID must be at least 4 characters and phone must be valid.',
      );
      return;
    }
    if (_password.text.length < 6) {
      setState(() => _error = 'Password must be at least 6 characters.');
      return;
    }
    if (_password.text != _confirm.text) {
      setState(() => _error = 'Passwords do not match.');
      return;
    }
    setState(() {
      _error = '';
      _busy = true;
    });
    try {
      if (AppConfig.isProduction) {
        // The backend deliberately does NOT authenticate on register; the
        // user follows with an explicit login.
        await BackendGateway.instance.signup(
          name: _name.text.trim(),
          email: email,
          studentId: _id.text.trim(),
          password: _password.text,
        );
        if (!mounted) return;
        widget.onSuccess();
        return;
      }
      // Demo mode: local session only.
      await AppStore.instance.signup(
        name: _name.text.trim(),
        email: email,
        studentId: _id.text.trim(),
      );
      if (mounted) widget.onSuccess();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Something went wrong. Please try again.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _id.dispose();
    _phone.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AuthShell(
      title: 'Create your account',
      subtitle: 'Join your campus community and make an impact.',
      onBack: widget.onBack,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          AuthTextField(
            label: 'Full name',
            hint: 'e.g. Emma Johnson',
            controller: _name,
          ),
          const SizedBox(height: 16),
          AuthTextField(
            label: 'Email',
            hint: 'e.g. emma@campus.edu',
            controller: _email,
            keyboardType: TextInputType.emailAddress,
          ),
          const SizedBox(height: 16),
          AuthTextField(
            label: 'Student ID',
            hint: 'e.g. ECO-2024-001',
            controller: _id,
          ),
          const SizedBox(height: 16),
          AuthTextField(
            label: 'Phone number',
            hint: 'e.g. +1 555 123 4567',
            controller: _phone,
            keyboardType: TextInputType.phone,
          ),
          const SizedBox(height: 16),
          AuthTextField(
            label: 'Password',
            hint: 'At least 6 characters',
            controller: _password,
            obscure: true,
          ),
          const SizedBox(height: 16),
          AuthTextField(
            label: 'Confirm password',
            hint: 'Re-enter your password',
            controller: _confirm,
            obscure: true,
          ),
          if (_error.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              _error,
              style: const TextStyle(
                color: AppColors.red,
                fontSize: 12,
                height: 1.4,
              ),
            ),
          ],
          const SizedBox(height: 8),
          PrimaryButton(
            label: _busy ? 'Creating account…' : 'Sign up',
            onTap: _busy ? null : _submit,
          ),
          const SizedBox(height: 22),
          Wrap(
            alignment: WrapAlignment.center,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              const Text(
                'Already have an account? ',
                style: TextStyle(
                  color: AppColors.mutedForeground,
                  fontSize: 12,
                ),
              ),
              GestureDetector(
                onTap: widget.onLogin,
                child: const Text(
                  'Login',
                  style: TextStyle(
                    color: AppColors.darkGreen,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    decoration: TextDecoration.underline,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------

class Home extends StatelessWidget {
  const Home({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    final store = AppStore.instance;
    final unreadCount = store.notifications.where((n) => !n.read).length;
    final summary = ImpactCalculator.summarize(store.contributions);
    final cupTop = AppRepositories.instance.leaderboardSync('Weekly').first;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Hi, ${store.user?.firstName ?? 'there'}!',
                      style: const TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      "Let's make a difference today",
                      style: const TextStyle(
                        color: AppColors.mutedForeground,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              IconButton(
                onPressed: () => go(Screen.notifications),
                icon: Stack(
                  clipBehavior: Clip.none,
                  children: [
                    const Icon(Icons.notifications_none, size: 22),
                    if (unreadCount > 0)
                      Positioned(
                        right: -4,
                        top: -3,
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 4,
                            vertical: 1,
                          ),
                          constraints: const BoxConstraints(
                            minWidth: 16,
                            minHeight: 16,
                          ),
                          alignment: Alignment.center,
                          decoration: const BoxDecoration(
                            color: AppColors.notice,
                            shape: BoxShape.circle,
                          ),
                          child: Text(
                            unreadCount > 9 ? '9+' : '$unreadCount',
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 8,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          const PointsCard(),
          const SizedBox(height: 26),
          const SectionHeading('Quick Actions'),
          InkWell(
            onTap: () {
              AppStore.instance.prepareRecycle();
              go(Screen.station);
            },
            borderRadius: BorderRadius.circular(15),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [AppColors.splashTop, AppColors.darkGreen],
                ),
                borderRadius: BorderRadius.circular(15),
              ),
              child: Row(
                children: [
                  Container(
                    width: 42,
                    height: 42,
                    decoration: const BoxDecoration(
                      color: Color(0xFF1cc766),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(
                      Icons.recycling,
                      color: Colors.white,
                      size: 22,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: const [
                        Text(
                          'Recycle Now',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 14,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        SizedBox(height: 3),
                        Text(
                          'Recycle your waste at an SCWT Smart Station',
                          style: TextStyle(
                            color: Color(0xFFc9ecd9),
                            fontSize: 10,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const Icon(
                    Icons.chevron_right,
                    color: Colors.white70,
                    size: 18,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),
          InkWell(
            onTap: () => go(Screen.schedule),
            borderRadius: BorderRadius.circular(13),
            child: Container(
              padding: const EdgeInsets.all(13),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: const Color(0xFFdcefe4)),
                borderRadius: BorderRadius.circular(13),
              ),
              child: Row(
                children: [
                  Container(
                    width: 34,
                    height: 34,
                    decoration: BoxDecoration(
                      color: AppColors.lightGreenBg,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: const Icon(
                      Icons.inventory_2,
                      size: 18,
                      color: AppColors.primary,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: const [
                        Text(
                          'Schedule Collection',
                          style: TextStyle(
                            fontSize: 12,
                            color: AppColors.foreground,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        SizedBox(height: 3),
                        Text(
                          'For larger quantities of recyclable material',
                          style: TextStyle(
                            fontSize: 10,
                            color: AppColors.mutedForeground,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const Icon(
                    Icons.chevron_right,
                    size: 16,
                    color: Color(0xFFa4b3ac),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 24),
          const SectionHeading('Collection Status'),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: const Color(0xFFf1faf5),
              border: Border.all(color: const Color(0xFFdcefe4)),
              borderRadius: BorderRadius.circular(13),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Builder(
                    builder: (context) {
                      final req = store.collectionRequests.isEmpty
                          ? null
                          : store.collectionRequests.first;
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: req == null
                            ? const [
                                Text(
                                  'No collection requests yet',
                                  style: TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                SizedBox(height: 6),
                                Text(
                                  'Plan a campus collection for bulk recyclable material',
                                  style: TextStyle(
                                    fontSize: 11,
                                    color: AppColors.successGreen,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ]
                            : [
                                Text(
                                  'Latest request ${req.id}',
                                  style: const TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  '${req.materialType} · ${req.estimatedQuantity} · ${req.collectionPoint}',
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: AppColors.successGreen,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  req.statusLabel,
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: AppColors.statusYellow,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ],
                      );
                    },
                  ),
                ),
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(
                    color: AppColors.statusYellow,
                    borderRadius: BorderRadius.circular(9),
                  ),
                  child: const Icon(
                    Icons.inventory_2,
                    size: 17,
                    color: Colors.white,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          InkWell(
            onTap: () => go(Screen.impact),
            borderRadius: BorderRadius.circular(15),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: const Color(0xFFdcefe4)),
                borderRadius: BorderRadius.circular(15),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Your impact',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          '${summary.monthWeightKg.toStringAsFixed(1)} kg',
                          style: const TextStyle(
                            fontSize: 24,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        Text(
                          summary.monthWeightKg > 0
                              ? 'recycled this month'
                              : 'No recycling this month yet',
                          style: const TextStyle(
                            color: AppColors.mutedForeground,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const LeafMark(),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          InkWell(
            onTap: () => go(Screen.leaderboard),
            borderRadius: BorderRadius.circular(15),
            child: Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: const Color(0xFFdcefe4)),
                borderRadius: BorderRadius.circular(15),
              ),
              child: Row(
                children: [
                  Container(
                    width: 42,
                    height: 42,
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFF6E3),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Icon(
                      Icons.emoji_events,
                      size: 22,
                      color: AppColors.statusYellow,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Faculty Cup',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 5),
                        Row(
                          children: [
                            Flexible(
                              child: Text(
                                cupTop.facultyName,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 11,
                                  color: AppColors.foreground,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                            const SizedBox(width: 6),
                            Text(
                              '#${cupTop.rank}',
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppColors.statusYellow,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Flexible(
                              child: Text(
                                '${_formatNum(cupTop.points)} pts',
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AppColors.mutedForeground,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const Icon(
                    Icons.chevron_right,
                    size: 16,
                    color: Color(0xFFa4b3ac),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

String _formatNum(int n) => n.toString().replaceAllMapped(
  RegExp(r'(\d)(?=(\d{3})+$)'),
  (m) => '${m[1]},',
);

class PointsCard extends StatelessWidget {
  const PointsCard({super.key});
  @override
  Widget build(BuildContext context) {
    final summary = ImpactCalculator.summarize(AppStore.instance.contributions);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFFf0faf4), Color(0xFFe4f5ec)],
        ),
        border: Border.all(color: const Color(0xFFd7ece0)),
        borderRadius: BorderRadius.circular(15),
      ),
      child: Row(
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Total Points',
                style: TextStyle(fontSize: 11, color: Color(0xFF5f7069)),
              ),
              const SizedBox(height: 3),
              Text(
                '${AppStore.instance.points}',
                style: const TextStyle(
                  fontSize: 29,
                  letterSpacing: -0.5,
                  fontWeight: FontWeight.w700,
                ),
              ),
              Text(
                summary.weekPoints > 0
                    ? '+${summary.weekPoints} this week'
                    : 'Earn points by recycling',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.successGreen,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const Spacer(),
          const Icon(Icons.eco, size: 31, color: Color(0xFF39ad57)),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Schedule Collection (bulk campus material)
// ---------------------------------------------------------------------------

class ScheduleCollection extends StatefulWidget {
  const ScheduleCollection({super.key, required this.go});
  final Go go;
  @override
  State<ScheduleCollection> createState() => _ScheduleCollectionState();
}

class _ScheduleCollectionState extends State<ScheduleCollection> {
  String waste = 'Plastic';
  String quantity = collectionQuantities.first;
  String point = collectionPoints.first;
  final List<String> dates = upcomingCollectionDates();
  late String date;
  String window = collectionWindows.first;

  @override
  void initState() {
    super.initState();
    date = dates.first;
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Schedule Collection', back: true, go: widget.go),
          const SizedBox(height: 5),
          Center(
            child: Container(
              width: 112,
              height: 112,
              decoration: BoxDecoration(
                border: Border.all(color: const Color(0xFFbde6ce), width: 2),
                borderRadius: BorderRadius.circular(22),
              ),
              child: const Icon(
                Icons.inventory_2,
                size: 55,
                color: AppColors.darkGreen,
              ),
            ),
          ),
          const SizedBox(height: 20),
          const Text(
            'For larger quantities of recyclable material\n(faculty events, departments, campus areas)',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, height: 1.5),
          ),
          const SizedBox(height: 22),
          const SectionHeading('Material'),
          SizedBox(
            height: 32,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: ['Plastic', 'Metal', 'Paper', 'Other'].map((item) {
                return _chip(item, waste, (v) => setState(() => waste = v));
              }).toList(),
            ),
          ),
          const SizedBox(height: 18),
          const SectionHeading('Estimated Quantity'),
          SizedBox(
            height: 32,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: collectionQuantities.map((item) {
                return _chip(
                  item,
                  quantity,
                  (v) => setState(() => quantity = v),
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 18),
          const SectionHeading('Collection Point'),
          SizedBox(
            height: 32,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: collectionPoints.map((item) {
                return _chip(item, point, (v) => setState(() => point = v));
              }).toList(),
            ),
          ),
          const SizedBox(height: 18),
          const SectionHeading('Preferred Date'),
          SizedBox(
            height: 32,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: dates.map((item) {
                return _chip(item, date, (v) => setState(() => date = v));
              }).toList(),
            ),
          ),
          const SizedBox(height: 18),
          const SectionHeading('Time Window'),
          SizedBox(
            height: 32,
            child: ListView(
              scrollDirection: Axis.horizontal,
              children: collectionWindows.map((item) {
                return _chip(item, window, (v) => setState(() => window = v));
              }).toList(),
            ),
          ),
          const SizedBox(height: 24),
          PrimaryButton(
            label: 'Request Collection',
            icon: Icons.inventory_2,
            onTap: () async {
              await AppStore.instance.requestCollection(
                materialType: waste,
                estimatedQuantity: quantity,
                collectionPoint: point,
                preferredDate: date,
                timeWindow: window,
              );
              if (context.mounted) widget.go(Screen.collectionCreated);
            },
          ),
        ],
      ),
    );
  }

  Widget _chip(String value, String selected, ValueChanged<String> onSelected) {
    final active = selected == value;
    return Padding(
      padding: const EdgeInsets.only(right: 7),
      child: ChoiceChip(
        label: Text(value, style: const TextStyle(fontSize: 11)),
        selected: active,
        onSelected: (_) => onSelected(value),
        selectedColor: AppColors.darkGreen,
        labelStyle: TextStyle(
          color: active ? Colors.white : AppColors.mutedForeground,
          fontWeight: FontWeight.w600,
          fontSize: 11,
        ),
        backgroundColor: Colors.white,
        side: BorderSide(
          color: active ? AppColors.darkGreen : AppColors.border,
        ),
        showCheckmark: false,
        padding: EdgeInsets.zero,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Rewards
// ---------------------------------------------------------------------------

class Rewards extends StatelessWidget {
  const Rewards({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        gradient: RadialGradient(
          radius: 1.4,
          colors: [Color(0xFF148c4c), Color(0xFF006045), Color(0xFF003d30)],
        ),
      ),
      child: _RewardsBody(go: go),
    );
  }
}

class _RewardsBody extends StatefulWidget {
  const _RewardsBody({required this.go});
  final Go go;
  @override
  State<_RewardsBody> createState() => _RewardsBodyState();
}

class _RewardsBodyState extends State<_RewardsBody> {
  // Production mode: the catalog and balances come from the SCWT backend;
  // redemption is a server-side atomic deduction. Demo mode: local catalog.
  List<BackendReward>? _catalog;
  String? _loadError;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    if (AppConfig.isProduction) _loadCatalog();
  }

  Future<void> _loadCatalog() async {
    setState(() => _loading = true);
    try {
      final cat = await BackendGateway.instance.fetchRewards();
      if (!mounted) return;
      setState(() {
        _catalog = cat.rewards;
        _loadError = null;
        _loading = false;
      });
      await AppStore.instance.updateBackendPoints(cat.balance);
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _loadError = e.message;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _confirmRedemptionOption(
    BuildContext context,
    RewardOption reward,
  ) async {
    final store = AppStore.instance;
    if (store.points < reward.cost) {
      showToastError(
        context,
        'You need ${reward.cost - store.points} more EcoPoints for this reward.',
      );
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Colors.white,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Text(
          'Redeem ${reward.cost} EcoPoints?',
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
        ),
        content: Text(
          'Confirm to redeem ${reward.label} — ${reward.partner}.',
          style: const TextStyle(
            fontSize: 12,
            color: AppColors.mutedForeground,
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text(
              'Cancel',
              style: TextStyle(
                color: AppColors.mutedForeground,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text(
              'Confirm',
              style: TextStyle(
                color: AppColors.darkGreen,
                fontSize: 12,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      final result = await store.redeemReward(
        rewardId: reward.id,
        cost: reward.cost,
      );
      if (!context.mounted) return;
      setState(() {}); // refresh balance display
      if (result == RedeemResult.success) {
        showToast(context, 'Redeemed ${reward.label} — ${reward.partner}');
      } else {
        showToastError(context, 'Not enough EcoPoints.');
      }
    }
  }

  /// PRODUCTION: POST /rewards/{id}/redeem — the BACKEND validates the
  /// balance and deducts atomically. The client never computes the result.
  Future<void> _confirmRedemptionBackend(
    BuildContext context,
    BackendReward reward,
  ) async {
    if (AppStore.instance.points < reward.pointsCost) {
      showToastError(
        context,
        'You need ${reward.pointsCost - AppStore.instance.points} more EcoPoints for this reward.',
      );
      return;
    }
    String? destination;
    if (reward.requiresDestination) {
      destination = await showDialog<String>(
        context: context,
        builder: (ctx) {
          final controller = TextEditingController();
          return AlertDialog(
            backgroundColor: Colors.white,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
            title: Text(
              'Redeem ${reward.name}?',
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
            ),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${reward.valueLabel} — ${reward.provider}.\nEnter the mobile number or handle that should receive it:',
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.mutedForeground,
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: controller,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                    hintText: 'e.g. 01001234567',
                  ),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text(
                  'Cancel',
                  style: TextStyle(
                    color: AppColors.mutedForeground,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              TextButton(
                onPressed: () => Navigator.pop(ctx, controller.text.trim()),
                child: const Text(
                  'Confirm',
                  style: TextStyle(
                    color: AppColors.darkGreen,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          );
        },
      );
      if (destination == null || destination.isEmpty) return; // cancelled
    } else {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          title: Text(
            'Redeem ${reward.pointsCost} EcoPoints?',
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
          ),
          content: Text(
            'Confirm to redeem ${reward.name} — ${reward.valueLabel}.',
            style: const TextStyle(
              fontSize: 12,
              color: AppColors.mutedForeground,
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text(
                'Cancel',
                style: TextStyle(
                  color: AppColors.mutedForeground,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text(
                'Confirm',
                style: TextStyle(
                  color: AppColors.darkGreen,
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }

    try {
      final balance = await BackendGateway.instance.redeemReward(
        rewardId: reward.id,
        destination: destination,
      );
      if (!context.mounted) return;
      await AppStore.instance.updateBackendPoints(balance);
      if (!context.mounted) return;
      setState(() {}); // refresh balance display
      showToast(context, 'Redeemed ${reward.name} — ${reward.valueLabel}');
    } on ApiException catch (e) {
      if (context.mounted) showToastError(context, e.message);
    } catch (_) {
      if (context.mounted) {
        showToastError(
          context,
          'Cannot reach SCWT right now. Please try again.',
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final points = AppStore.instance.points;
    final summary = ImpactCalculator.summarize(AppStore.instance.contributions);
    final header = Row(
      children: [
        IconButton(
          icon: const Icon(
            Icons.arrow_back_ios_new,
            size: 20,
            color: Colors.white,
          ),
          onPressed: () => widget.go(Screen.home),
        ),
        Expanded(
          child: Center(
            child: Text(
              'Rewards',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w800,
                color: Colors.white.withValues(alpha: 0.95),
              ),
            ),
          ),
        ),
        const SizedBox(width: 48),
      ],
    );

    final Widget catalogSection;
    if (AppConfig.isProduction) {
      catalogSection = _backendCatalogSection(points);
    } else {
      catalogSection = _demoCatalogSection(context, points);
    }

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          header,
          const SizedBox(height: 10),
          Center(
            child: Container(
              width: 61,
              height: 61,
              decoration: const BoxDecoration(
                color: Color(0xFF1cc766),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.emoji_events,
                color: Colors.white,
                size: 35,
              ),
            ),
          ),
          const SizedBox(height: 12),
          const Text(
            'Your Points',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.white, fontSize: 13),
          ),
          const SizedBox(height: 6),
          Text(
            '$points',
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 32,
              fontWeight: FontWeight.w700,
            ),
          ),
          Text(
            summary.weekPoints > 0
                ? '+${summary.weekPoints} this week'
                : 'Recycle to earn points',
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white70, fontSize: 11),
          ),
          const SizedBox(height: 20),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(15),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Redeem your points',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 16),
                catalogSection,
                const SizedBox(height: 18),
                PrimaryButton(
                  label: 'How it works',
                  onTap: () => showDialog<void>(
                    context: context,
                    builder: (ctx) => AlertDialog(
                      backgroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(16),
                      ),
                      title: const Text(
                        'Earning EcoPoints',
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      content: const Text(
                        'Every verified deposit at an SCWT Smart Station earns points based on the material:\n\nPlastic 10 · Metal 15 · Paper 8 · Other 5\n\nRedeem your points once you have enough for a reward.',
                        style: TextStyle(
                          fontSize: 12,
                          height: 1.5,
                          color: AppColors.mutedForeground,
                        ),
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(ctx),
                          child: const Text(
                            'Got it',
                            style: TextStyle(
                              color: AppColors.darkGreen,
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// DEMO catalog: fixed local options, local deduction.
  Widget _demoCatalogSection(BuildContext context, int points) {
    return Row(
      children: [
        for (var i = 0; i < rewardCatalog.length; i++) ...[
          if (i > 0) const SizedBox(width: 7),
          Expanded(
            child: _RewardOption(
              option: rewardCatalog[i],
              onTap: () => _confirmRedemptionOption(context, rewardCatalog[i]),
            ),
          ),
        ],
      ],
    );
  }

  /// PRODUCTION catalog: loaded from GET /rewards; server-side redemption.
  Widget _backendCatalogSection(int points) {
    if (_loading) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(16),
          child: CircularProgressIndicator(color: AppColors.primary),
        ),
      );
    }
    if (_loadError != null) {
      return Column(
        children: [
          Text(
            _loadError!,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: 11,
              color: AppColors.mutedForeground,
            ),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _loadCatalog,
            child: const Text(
              'Retry',
              style: TextStyle(
                color: AppColors.darkGreen,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      );
    }
    final rewards = _catalog ?? const <BackendReward>[];
    if (rewards.isEmpty) {
      return const Text(
        'No rewards are available right now.',
        textAlign: TextAlign.center,
        style: TextStyle(fontSize: 11, color: AppColors.mutedForeground),
      );
    }
    return Row(
      children: [
        for (var i = 0; i < rewards.length && i < 3; i++) ...[
          if (i > 0) const SizedBox(width: 7),
          Expanded(
            child: _BackendRewardOption(
              reward: rewards[i],
              onTap: () => _confirmRedemptionBackend(context, rewards[i]),
            ),
          ),
        ],
      ],
    );
  }
}

/// Production reward tile driven entirely by backend catalog data.
class _BackendRewardOption extends StatelessWidget {
  const _BackendRewardOption({required this.reward, required this.onTap});
  final BackendReward reward;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final affordable = AppStore.instance.points >= reward.pointsCost;
    return InkWell(
      onTap: onTap,
      child: Opacity(
        opacity: affordable ? 1 : 0.55,
        child: Column(
          children: [
            Container(
              width: 43,
              height: 39,
              decoration: BoxDecoration(
                color: const Color(0xFFeef9f2),
                borderRadius: BorderRadius.circular(9),
              ),
              child: Icon(
                rewardIcon(reward.icon),
                size: 18,
                color: const Color(0xFF168b50),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              reward.name,
              textAlign: TextAlign.center,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 10, color: AppColors.foreground),
            ),
            Text(
              reward.provider,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 10,
                color: AppColors.mutedForeground,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              '${reward.pointsCost} pts · ${reward.valueLabel}',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w800,
                color: affordable
                    ? AppColors.successGreen
                    : AppColors.statusYellow,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RewardOption extends StatelessWidget {
  const _RewardOption({required this.option, required this.onTap});
  final RewardOption option;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final affordable = AppStore.instance.points >= option.cost;
    return InkWell(
      onTap: onTap,
      child: Opacity(
        opacity: affordable ? 1 : 0.55,
        child: Column(
          children: [
            Container(
              width: 43,
              height: 39,
              decoration: BoxDecoration(
                color: const Color(0xFFeef9f2),
                borderRadius: BorderRadius.circular(9),
              ),
              child: Icon(
                option.icon,
                size: 18,
                color: const Color(0xFF168b50),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              option.label,
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 10, color: AppColors.foreground),
            ),
            Text(
              option.partner,
              style: const TextStyle(
                fontSize: 10,
                color: AppColors.mutedForeground,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              '${option.cost} pts',
              style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w800,
                color: affordable
                    ? AppColors.successGreen
                    : AppColors.statusYellow,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _BreakdownRow extends StatelessWidget {
  const _BreakdownRow({
    required this.label,
    required this.value,
    this.bold = false,
    this.muted = false,
  });
  final String label;
  final String value;
  final bool bold;
  final bool muted;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 12),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFFedf4ef))),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: TextStyle(
                fontSize: 11,
                color: muted ? AppColors.mutedForeground : AppColors.foreground,
                fontWeight: bold ? FontWeight.w800 : FontWeight.w500,
              ),
            ),
          ),
          Text(
            value,
            style: TextStyle(
              fontSize: 11,
              fontWeight: bold ? FontWeight.w800 : FontWeight.w600,
              color: muted ? AppColors.successGreen : AppColors.foreground,
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Impact
// ---------------------------------------------------------------------------

class Impact extends StatefulWidget {
  const Impact({super.key, required this.go});
  final Go go;
  @override
  State<Impact> createState() => _ImpactState();
}

class _ImpactState extends State<Impact> {
  @override
  Widget build(BuildContext context) {
    final summary = ImpactCalculator.summarize(AppStore.instance.contributions);
    // Estimated conversions (kg -> CO2 / trees / energy / water). Factors live
    // in impact.dart so they can be tuned or backend-driven later.
    final metrics = [
      (
        'Waste Recycled',
        summary.totalWeightKg,
        'kg',
        Icons.recycling,
        AppColors.orange,
      ),
      (
        'CO₂ Reduced (est.)',
        summary.co2Kg,
        'kg',
        Icons.waves,
        AppColors.purple,
      ),
      ('Trees Saved (est.)', summary.trees, '', Icons.eco, AppColors.green),
      (
        'Energy Saved (est.)',
        summary.energyKwh,
        'kWh',
        Icons.bolt,
        AppColors.violet,
      ),
      (
        'Water Saved (est.)',
        summary.waterLiters,
        'L',
        Icons.water_drop,
        AppColors.blue,
      ),
    ];
    String fmt(double v) =>
        v >= 10 ? v.toStringAsFixed(0) : v.toStringAsFixed(1);

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'Your Impact', back: true, go: widget.go),
          const SizedBox(height: 6),
          Text(
            summary.depositCount == 0
                ? 'Your impact is calculated from your verified deposits at SCWT stations.'
                : 'Based on ${summary.depositCount} verified deposit${summary.depositCount == 1 ? '' : 's'}.',
            style: const TextStyle(
              fontSize: 11,
              color: AppColors.mutedForeground,
            ),
          ),
          const SizedBox(height: 15),
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFFe0eee6)),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              children: List.generate(metrics.length, (i) {
                final m = metrics[i];
                final last = i == metrics.length - 1;
                return Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 11,
                  ),
                  decoration: BoxDecoration(
                    border: last
                        ? null
                        : const Border(
                            bottom: BorderSide(color: Color(0xFFedf4ef)),
                          ),
                  ),
                  child: Row(
                    children: [
                      Container(
                        width: 25,
                        height: 25,
                        decoration: BoxDecoration(
                          color: m.$5,
                          shape: BoxShape.circle,
                        ),
                        child: Icon(m.$4, size: 14, color: Colors.white),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          m.$1,
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.foreground,
                          ),
                        ),
                      ),
                      Text(
                        '${fmt(m.$2)}${m.$3.isEmpty ? '' : ' ${m.$3}'}',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                );
              }),
            ),
          ),
          const SizedBox(height: 20),
          const SectionHeading('Material Breakdown'),
          const SizedBox(height: 10),
          Container(
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFFe0eee6)),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              children: [
                _BreakdownRow(
                  label: 'Total Recycled',
                  value: '${summary.totalWeightKg.toStringAsFixed(1)} kg',
                  bold: true,
                ),
                if (summary.byMaterial.isEmpty)
                  const _BreakdownRow(label: 'No deposits yet', value: '0 kg')
                else
                  ...summary.byMaterial.map(
                    (b) => _BreakdownRow(label: b.material, value: b.display),
                  ),
                _BreakdownRow(
                  label: 'Estimated Material Value',
                  value: '${summary.estimatedValueEgp} EGP',
                  bold: true,
                  muted: true,
                ),
              ],
            ),
          ),
          const SizedBox(height: 17),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFFf3faf6), Color(0xFFe4f4ea)],
              ),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Total CO₂ Reduced (est.)',
                        style: TextStyle(
                          fontSize: 10,
                          color: AppColors.mutedForeground,
                        ),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        '${summary.co2Kg.toStringAsFixed(1)} kg',
                        style: const TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      Text(
                        summary.totalWeightKg > 0
                            ? 'from all your deposits'
                            : 'No deposits yet',
                        style: const TextStyle(
                          fontSize: 10,
                          color: AppColors.mutedForeground,
                        ),
                      ),
                    ],
                  ),
                ),
                const LeafMark(),
              ],
            ),
          ),
          const SizedBox(height: 24),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Expanded(
                child: Text(
                  'Monthly progress',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
                ),
              ),
              Flexible(
                child: Text(
                  '${summary.monthWeightKg.toStringAsFixed(1)} kg this month',
                  textAlign: TextAlign.end,
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppColors.successGreen,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          _MonthlyChart(contributions: AppStore.instance.contributions),
        ],
      ),
    );
  }
}

/// Last 6 months of recycled weight, derived from real deposits.
class _MonthlyChart extends StatelessWidget {
  const _MonthlyChart({required this.contributions});
  final List<Contribution> contributions;

  @override
  Widget build(BuildContext context) {
    const monthLabels = [
      'Jan',
      'Feb',
      'Mar',
      'Apr',
      'May',
      'Jun',
      'Jul',
      'Aug',
      'Sep',
      'Oct',
      'Nov',
      'Dec',
    ];
    final now = DateTime.now();
    final buckets = List.generate(6, (i) {
      final d = DateTime(now.year, now.month - (5 - i));
      return (
        label: monthLabels[d.month - 1],
        isCurrent: d.year == now.year && d.month == now.month,
        grams: 0.0,
      );
    });
    for (final c in contributions) {
      for (var i = 0; i < buckets.length; i++) {
        final b = buckets[i];
        final d = DateTime(now.year, now.month - (5 - i));
        if (c.timestamp.year == d.year && c.timestamp.month == d.month) {
          buckets[i] = (
            label: b.label,
            isCurrent: b.isCurrent,
            grams: b.grams + c.weight,
          );
        }
      }
    }
    final maxG = buckets.map((b) => b.grams).fold(0.0, max);
    return Container(
      height: 150,
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 0),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: buckets.map((b) {
          final height = b.grams <= 0
              ? 4.0
              : 30.0 + 90.0 * (b.grams / (maxG <= 0 ? 1 : maxG));
          return Column(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              Container(
                width: 18,
                height: height,
                decoration: BoxDecoration(
                  color: b.isCurrent
                      ? AppColors.darkGreen
                      : const Color(0xFF4fcb78),
                  borderRadius: const BorderRadius.vertical(
                    top: Radius.circular(4),
                  ),
                ),
              ),
              const SizedBox(height: 7),
              Text(
                b.label,
                style: const TextStyle(
                  fontSize: 9,
                  color: AppColors.mutedForeground,
                ),
              ),
            ],
          );
        }).toList(),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Profile List screen (generic)
// ---------------------------------------------------------------------------

class Profile extends StatelessWidget {
  const Profile({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    final store = AppStore.instance;
    final user = store.user;
    const appVersion = '1.0.0';
    Future<void> confirmLogout() async {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          title: const Text(
            'Log out?',
            style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
          ),
          content: const Text(
            'Your account data will be removed from this device.',
            style: TextStyle(fontSize: 12, color: AppColors.mutedForeground),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text(
                'Cancel',
                style: TextStyle(
                  color: AppColors.mutedForeground,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text(
                'Log out',
                style: TextStyle(
                  color: AppColors.red,
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
          ],
        ),
      );
      if (confirmed == true) {
        if (AppConfig.isProduction) {
          // Revokes the backend token and clears local mirrors.
          await BackendGateway.instance.logout();
        } else {
          await store.logout();
        }
        if (context.mounted) {
          // Resets the app flow back to authentication (handled by main.dart).
          AppFlowNav.logoutAction(context)?.call();
        }
      }
    }

    final items = <(String, IconData, Screen?, void Function()?)>[
      ('My SCWT QR', Icons.qr_code, Screen.myQr, null),
      ('History', Icons.receipt_long, Screen.history, null),
      ('My Badges', Icons.workspace_premium, Screen.badges, null),
      ('Notifications', Icons.notifications_none, Screen.notifications, null),
      ('Faculty Cup', Icons.emoji_events, Screen.leaderboard, null),
    ];
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(go: go),
          const SizedBox(height: 6),
          Column(
            children: [
              Container(
                width: 82,
                height: 82,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: const Color(0xFFc8e8d3),
                  shape: BoxShape.circle,
                  border: Border.all(color: const Color(0xFFe5f2e9), width: 4),
                ),
                child: Text(
                  user?.initials ?? '?',
                  style: const TextStyle(
                    color: AppColors.darkGreen,
                    fontSize: 23,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                user?.name ?? 'SCWT Student',
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 5),
              Text(
                user?.email ?? '-',
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.mutedForeground,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                user?.studentId ?? '',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.mutedForeground,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 22),
          const PointsCard(),
          const SizedBox(height: 22),
          Column(
            children: items.map((e) {
              return InkWell(
                onTap: () => go(e.$3!),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    vertical: 14,
                    horizontal: 2,
                  ),
                  decoration: const BoxDecoration(
                    border: Border(
                      bottom: BorderSide(color: Color(0xFFedf4ef)),
                    ),
                  ),
                  child: Row(
                    children: [
                      Icon(e.$2, size: 18, color: const Color(0xFF72827b)),
                      const SizedBox(width: 12),
                      Text(
                        e.$1,
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.foreground,
                        ),
                      ),
                      const Spacer(),
                      const Icon(
                        Icons.chevron_right,
                        size: 15,
                        color: Color(0xFFa4b3ac),
                      ),
                    ],
                  ),
                ),
              );
            }).toList(),
          ),
          InkWell(
            onTap: () => showToast(context, 'Help Center is coming soon.'),
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 2),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: Color(0xFFedf4ef))),
              ),
              child: Row(
                children: [
                  Icon(
                    Icons.help_outline,
                    size: 18,
                    color: const Color(0xFF72827b),
                  ),
                  const SizedBox(width: 12),
                  Text(
                    'Help Center',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.foreground,
                    ),
                  ),
                  const Spacer(),
                  const Icon(
                    Icons.chevron_right,
                    size: 15,
                    color: Color(0xFFa4b3ac),
                  ),
                ],
              ),
            ),
          ),
          InkWell(
            onTap: confirmLogout,
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 2),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: Color(0xFFedf4ef))),
              ),
              child: Row(
                children: [
                  Icon(Icons.logout, size: 18, color: AppColors.red),
                  const SizedBox(width: 12),
                  Text(
                    'Logout',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.red,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                ],
              ),
            ),
          ),
          const SizedBox(height: 18),
          Center(
            child: Text(
              'SCWT v$appVersion',
              style: const TextStyle(fontSize: 10, color: Color(0xFFa4b3ac)),
            ),
          ),
        ],
      ),
    );
  }
}

class History extends StatelessWidget {
  const History({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    final contributions = AppStore.instance.contributions;
    final requests = AppStore.instance.collectionRequests;
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 110),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'History', back: true, go: go),
          const SizedBox(height: 10),
          const SectionHeading('Recycling Transactions'),
          const SizedBox(height: 8),
          if (contributions.isEmpty)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFFf7faf8),
                borderRadius: BorderRadius.circular(13),
              ),
              child: const Text(
                'No recycling transactions yet.\nRecycle at an SCWT Smart Station to see your deposits here.',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 11,
                  color: AppColors.mutedForeground,
                  height: 1.5,
                ),
              ),
            )
          else
            Column(
              children: contributions.map((c) {
                return InkWell(
                  onTap: () {
                    AppStore.instance.currentContribution = c;
                    go(Screen.contributionDetail);
                  },
                  borderRadius: BorderRadius.circular(13),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(13),
                    decoration: BoxDecoration(
                      border: Border.all(color: const Color(0xFFe0eee6)),
                      borderRadius: BorderRadius.circular(13),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 35,
                          height: 35,
                          decoration: BoxDecoration(
                            color: const Color(0xFFeaf8ef),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: const Icon(
                            Icons.recycling,
                            size: 18,
                            color: AppColors.successGreen,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '${c.materialType} recycling',
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '${c.dateDisplay} · ${c.weightDisplay}',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AppColors.mutedForeground,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Text(
                          '+${c.points} pts',
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.successGreen,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Container(
                          width: 19,
                          height: 19,
                          decoration: const BoxDecoration(
                            color: AppColors.primary,
                            shape: BoxShape.circle,
                          ),
                          child: const Icon(
                            Icons.check,
                            size: 12,
                            color: Colors.white,
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
          const SizedBox(height: 8),
          const SectionHeading('Collection Requests'),
          const SizedBox(height: 8),
          if (requests.isEmpty)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: const Color(0xFFf7faf8),
                borderRadius: BorderRadius.circular(13),
              ),
              child: const Text(
                'No collection requests yet. Bulk recyclable material\n(faculty events, departments) can be scheduled for collection.',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 11,
                  color: AppColors.mutedForeground,
                  height: 1.5,
                ),
              ),
            )
          else
            Column(
              children: requests.map((r) {
                return InkWell(
                  onTap: () {
                    AppStore.instance.currentCollectionRequest = r;
                    go(Screen.collectionCreated);
                  },
                  borderRadius: BorderRadius.circular(13),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(13),
                    decoration: BoxDecoration(
                      color: const Color(0xFFf1faf5),
                      border: Border.all(color: const Color(0xFFe0eee6)),
                      borderRadius: BorderRadius.circular(13),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 35,
                          height: 35,
                          decoration: BoxDecoration(
                            color: AppColors.lightGreenBg,
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: const Icon(
                            Icons.inventory_2,
                            size: 18,
                            color: AppColors.primary,
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                r.id,
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                              const SizedBox(height: 3),
                              Text(
                                '${r.materialType} · ${r.estimatedQuantity} · ${r.collectionPoint}',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AppColors.mutedForeground,
                                ),
                              ),
                              const SizedBox(height: 3),
                              Text(
                                '${r.preferredDate} · ${r.timeWindow}',
                                style: const TextStyle(
                                  fontSize: 10,
                                  color: AppColors.mutedForeground,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 4,
                          ),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFFf6e3),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            r.statusLabel,
                            style: const TextStyle(
                              fontSize: 9,
                              color: AppColors.statusYellow,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              }).toList(),
            ),
        ],
      ),
    );
  }
}

class Badges extends StatelessWidget {
  const Badges({super.key, required this.go});
  final Go go;
  @override
  Widget build(BuildContext context) {
    final unlockedMap = evaluateBadges(AppStore.instance.contributions);
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ScreenHeader(title: 'My Badges', back: true, go: go),
          const Text(
            'Badges unlock automatically from your verified deposits.',
            style: TextStyle(color: AppColors.mutedForeground, fontSize: 12),
          ),
          const SizedBox(height: 21),
          GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            childAspectRatio: 1.05,
            children: badgeCatalog.map((b) {
              final unlocked = unlockedMap[b.id] ?? false;
              return InkWell(
                onTap: () => showToast(
                  context,
                  unlocked
                      ? b.description
                      : '${b.title}: ${b.description.toLowerCase()}',
                ),
                borderRadius: BorderRadius.circular(15),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    vertical: 18,
                    horizontal: 8,
                  ),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: unlocked
                        ? const Color(0xFFf1faf5)
                        : const Color(0xFFf7faf8),
                    border: Border.all(color: const Color(0xFFe0eee6)),
                    borderRadius: BorderRadius.circular(15),
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        width: 52,
                        height: 52,
                        decoration: BoxDecoration(
                          color: unlocked
                              ? AppColors.primary
                              : const Color(0xFFd1dcd5),
                          shape: BoxShape.circle,
                        ),
                        child: Icon(b.icon, size: 25, color: Colors.white),
                      ),
                      const SizedBox(height: 7),
                      Text(
                        b.title,
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                          color: unlocked
                              ? AppColors.foreground
                              : const Color(0xFFa6b2ad),
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        unlocked ? 'Unlocked' : 'Locked',
                        style: TextStyle(
                          fontSize: 10,
                          color: unlocked
                              ? AppColors.mutedForeground
                              : const Color(0xFFa6b2ad),
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }
}
