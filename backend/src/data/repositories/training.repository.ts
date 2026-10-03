import { desc, eq } from 'drizzle-orm';
import { db } from '../db/client.js';
import { type NewTrainingJob, trainingJobs } from '../db/schema.js';

export async function createTrainingJob(data: NewTrainingJob): Promise<number> {
  const result = await db.insert(trainingJobs).values(data);

  return Number(result[0].insertId);
}

export async function getTrainingJob(id: number) {
  const rows = await db.select().from(trainingJobs).where(eq(trainingJobs.id, id)).limit(1);

  return rows[0] ?? null;
}

export async function getLatestTrainingJob() {
  const rows = await db.select().from(trainingJobs).orderBy(desc(trainingJobs.createdAt)).limit(1);

  return rows[0] ?? null;
}

export async function updateTrainingJob(
  id: number,
  data: Partial<typeof trainingJobs.$inferInsert>,
): Promise<void> {
  await db.update(trainingJobs).set(data).where(eq(trainingJobs.id, id));
}
