import { HttpResponse } from 'msw';

export type AuthCheckResult =
    | { authorized: true; token: string }
    | { authorized: false; response: HttpResponse<{ detail: string }> };

export function requireAuth(request: Request): AuthCheckResult {
    const auth = request.headers.get('Authorization');
    if (!auth || !auth.startsWith('Bearer ') || auth === 'Bearer ') {
        return {
            authorized: false,
            response: HttpResponse.json(
                { detail: 'Not authenticated' },
                { status: 401 },
            ),
        };
    }
    return { authorized: true, token: auth.slice(7) };
}

export function validationError(detail: string, fields?: Record<string, string[]>) {
    return HttpResponse.json(
        { detail, ...(fields && { errors: fields }) },
        { status: 422 },
    );
}

export function unauthorizedError(detail = 'Token 无效或已过期') {
    return HttpResponse.json({ detail }, { status: 401 });
}

export function serverError(detail = 'Internal Server Error') {
    return HttpResponse.json({ detail }, { status: 500 });
}
