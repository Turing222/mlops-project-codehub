import type { ZodType } from 'zod';

export const parseWithSchema = <T>(
    schema: ZodType<T>,
    input: unknown,
    errorMessage: string,
): T => {
    const result = schema.safeParse(input);
    if (result.success) {
        return result.data;
    }

    if (import.meta.env.DEV) {
        console.error(
            errorMessage,
            '\nValidation error:',
            JSON.stringify(result.error.format(), null, 2),
            '\nOriginal input:',
            JSON.stringify(input, null, 2)
        );
    }
    throw new Error(errorMessage);
};
