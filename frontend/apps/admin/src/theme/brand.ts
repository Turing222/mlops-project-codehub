/**
 * 品牌色预设的单一来源。App(data-brand 属性)与 UserProfileModal(选择器)共用;
 * 每个品牌在 index.css 有对应的 [data-brand='<key>'] 变量块。
 */
export type BrandKey = 'blue' | 'indigo' | 'purple' | 'teal' | 'orange';

export type BrandPreset = {
    key: BrandKey;
    value: string;
    gradientEnd: string;
};

export const BRAND_PRESETS: readonly BrandPreset[] = [
    { key: 'blue', value: '#1677ff', gradientEnd: '#722ed1' },
    { key: 'indigo', value: '#4f46e5', gradientEnd: '#9333ea' },
    { key: 'purple', value: '#722ed1', gradientEnd: '#db2777' },
    { key: 'teal', value: '#0d9488', gradientEnd: '#0284c7' },
    { key: 'orange', value: '#ea580c', gradientEnd: '#e11d48' },
];

export const DEFAULT_BRAND = BRAND_PRESETS[0];

export function brandKeyFor(color: string): BrandKey {
    return (BRAND_PRESETS.find((preset) => preset.value === color) ?? DEFAULT_BRAND).key;
}
