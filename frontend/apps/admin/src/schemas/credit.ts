import * as z from 'zod';

export const creditAccountResponseSchema = z.object({
  id: z.string().nullable(),
  user_id: z.string(),
  balance: z.number().int().nonnegative(),
  is_checked_in_today: z.boolean(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
});

export const checkinResponseSchema = z.object({
  success: z.boolean(),
  balance: z.number().int().nonnegative(),
  amount_earned: z.number().int().positive(),
  expires_at: z.string(),
});

export const creditTransactionResponseSchema = z.object({
  id: z.string(),
  account_id: z.string(),
  amount: z.number().int(),
  source: z.string(),
  expires_at: z.string().nullable().optional(),
  idempotency_key: z.string().nullable().optional(),
  created_at: z.string(),
});

export const creditTransactionsListResponseSchema = z.object({
  items: z.array(creditTransactionResponseSchema),
  total: z.number().int().nonnegative(),
});

export type CreditAccount = z.infer<typeof creditAccountResponseSchema>;
export type CheckinResponse = z.infer<typeof checkinResponseSchema>;
export type CreditTransaction = z.infer<typeof creditTransactionResponseSchema>;
export type CreditTransactionsList = z.infer<typeof creditTransactionsListResponseSchema>;
