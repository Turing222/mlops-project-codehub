/**
 * 浏览器 ingestion 端点的共享传输：优先 `navigator.sendBeacon`，失败回退 `fetch` keepalive。
 * 不感知具体遥测语义（error / metric），只负责把 payload 发出，且永不向调用方抛错。
 */
export const beaconPost = (url: string, payload: unknown): void => {
    try {
        const body = JSON.stringify(payload);

        if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
            const blob = new Blob([body], { type: 'application/json' });
            if (navigator.sendBeacon(url, blob)) {
                return;
            }
        }

        if (typeof fetch === 'function') {
            void fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                keepalive: true,
            }).catch(() => undefined);
        }
    } catch {
        // 传输失败绝不能影响用户侧请求流程。
    }
};
