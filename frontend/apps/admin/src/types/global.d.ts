export {};

declare global {
    interface Window {
        __refreshSidebar?: () => void | Promise<void>;
    }
}
