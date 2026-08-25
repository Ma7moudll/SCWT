import 'package:dio/dio.dart';

/// Error surfaced after mapping raw Dio/network failures to a friendly,
/// user-safe message (never a stack trace).
class ApiException implements Exception {
  final String message;
  final int? statusCode;

  const ApiException(this.message, {this.statusCode});

  bool get isUnauthorized => statusCode == 401;

  @override
  String toString() => message;
}

/// Thin HTTP client over Dio. Adds the stored Bearer token to every request
/// and normalizes all failures into [ApiException].
class ApiClient {
  final String baseUrl;
  final Dio _dio;
  String? _token;

  ApiClient(this.baseUrl)
    : _dio = Dio(
        BaseOptions(
          baseUrl: baseUrl,
          connectTimeout: const Duration(seconds: 12),
          receiveTimeout: const Duration(seconds: 20),
          headers: {'Accept': 'application/json'},
        ),
      ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          if (_token != null) {
            options.headers['Authorization'] = 'Bearer $_token';
          }
          handler.next(options);
        },
      ),
    );
  }

  void setToken(String? token) => _token = token;

  /// Currently held Bearer token (WebSocket auth uses `?token=` because
  /// sockets cannot send headers).
  String? get token => _token;

  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? query,
  }) async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        path,
        queryParameters: query,
      );
      return res.data ?? const {};
    } on DioException catch (e) {
      throw mapDio(e);
    }
  }

  Future<Map<String, dynamic>> post(String path, {Object? data}) async {
    return _send(() => _dio.post<Map<String, dynamic>>(path, data: data));
  }

  Future<Map<String, dynamic>> _send(
    Future<Response<Map<String, dynamic>>> Function() run,
  ) async {
    try {
      final res = await run();
      return res.data ?? const {};
    } on DioException catch (e) {
      throw mapDio(e);
    }
  }

  /// Maps any transport/HTTP failure to a professional message. The server's
  /// own `error`/`detail` sentence always wins; status-based texts are the
  /// fallbacks for degraded/offline paths.
  ApiException mapDio(DioException e) {
    return ApiException(_messageFor(e), statusCode: e.response?.statusCode);
  }

  String _messageFor(DioException e) {
    final data = e.response?.data;
    if (data is Map) {
      final error = data['error'] ?? data['detail'];
      if (error is String && error.trim().isNotEmpty) return error.trim();
    }
    switch (e.type) {
      case DioExceptionType.connectionError:
      case DioExceptionType.connectionTimeout:
        return 'Cannot reach Ecolamp right now. Please check your internet connection and try again.';
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return 'The connection timed out. Please try again.';
      case DioExceptionType.badResponse:
        break;
      case DioExceptionType.cancel:
        return 'The request was cancelled.';
      default:
        break;
    }
    switch (e.response?.statusCode) {
      case 401:
        return 'Please log in to continue.';
      case 403:
        return 'You do not have permission to perform this action.';
      case 404:
        return 'This item could not be found.';
      case 409:
        return 'This already exists. Please review the details and try again.';
      case 422:
        return 'Some of the details are invalid. Please review them and try again.';
      case 429:
        return 'Too many attempts. Please wait a moment and try again.';
      case int n when n >= 500:
        return 'Something went wrong on our side. Please try again shortly.';
      default:
        return 'Something went wrong. Please try again.';
    }
  }
}
