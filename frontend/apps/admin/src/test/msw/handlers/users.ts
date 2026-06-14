import { http } from 'msw';

import { API_URLS } from '../../../api/urls';
import { buildUser, buildUserImportResponse } from '../factories';
import { requireAuth, validationError } from '../utils';

export const userHandlers = [
    http.get(API_URLS.USER.ME, ({ request }) => {
        const auth = requireAuth(request);
        if (!auth.authorized) return auth.response;
        return Response.json(buildUser({ role: 'admin', is_superuser: true }));
    }),

    http.get(API_URLS.USER.QUERY, ({ request }) => {
        const auth = requireAuth(request);
        if (!auth.authorized) return auth.response;

        const url = new URL(request.url);
        const username = url.searchParams.get('username');
        const email = url.searchParams.get('email');

        if (!username && !email) {
            return validationError('username 或 email 至少提供一个');
        }

        return Response.json(
            buildUser({ username: username ?? undefined, email: email ?? undefined }),
        );
    }),

    http.patch(API_URLS.USER.UPDATE(':id'), async ({ request, params }) => {
        const auth = requireAuth(request);
        if (!auth.authorized) return auth.response;

        const id = params.id as string;
        if (id === 'not-found') {
            return Response.json({ detail: 'User not found' }, { status: 404 });
        }

        const body = await request.json();
        return Response.json(buildUser({ id, ...body as Record<string, unknown> }));
    }),

    http.post(API_URLS.USER.CSV_UPLOAD, async ({ request }) => {
        const auth = requireAuth(request);
        if (!auth.authorized) return auth.response;
        return Response.json(buildUserImportResponse());
    }),
];
