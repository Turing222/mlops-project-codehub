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

    console.error(errorMessage, result.error.flatten());
    throw new Error(errorMessage);
};
