import { http, HttpResponse } from 'msw';

import { API_URLS } from '../../../api/urls';
import { buildAuthResponse } from '../factories';
import { validationError } from '../utils';

export const authHandlers = [
    http.post(API_URLS.AUTH.LOGIN, async ({ request }) => {
        const body = await request.text();
        const params = new URLSearchParams(body);
        const username = params.get('username');
        const password = params.get('password');

        if (!username || !password) {
            return validationError('Field required');
        }

        if (username === 'bad-user' || password === 'wrong-pass') {
            return HttpResponse.json(
                { detail: 'Incorrect username or password' },
                { status: 401 },
            );
        }

        return HttpResponse.json(buildAuthResponse({ username }));
    }),
];
