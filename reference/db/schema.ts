import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';
export const records = sqliteTable('records', { id: text('id').primaryKey(), kind: text('kind').notNull(), data: text('data').notNull(), revision: integer('revision').notNull().default(0), lock: text('lock'), lockedAt: integer('locked_at') });
export const users = sqliteTable('users', { id: text('id').primaryKey(), email: text('email').notNull().unique(), name: text('name').notNull(), role: text('role').notNull(), password: text('password').notNull() });
export const sessions = sqliteTable('sessions', { id: text('id').primaryKey(), userId: text('user_id').notNull(), expires: integer('expires').notNull() });
export const executions = sqliteTable('executions', { id: text('id').primaryKey(), jobId: text('job_id').notNull(), action: text('action').notNull(), status: text('status').notNull(), data: text('data').notNull(), created: text('created').notNull() });
export const nonces = sqliteTable('nonces', { id: text('id').primaryKey(), created: integer('created').notNull() });
