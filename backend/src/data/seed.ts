import 'dotenv/config';

import { eq } from 'drizzle-orm';
import sharp from 'sharp';

import { db, pool } from './db/client.js';
import { categories, images } from './db/schema.js';
import { minioBucket, minioClient } from './storage/minio.client.js';
import { ensureMinioBucket } from './storage/minio.storage.js';

/**
 * Categorías de ejemplo.
 * El nombre es UNIQUE, por lo que el seeder puede ejecutarse varias veces
 * sin crear duplicados.
 */
const seedCategories = [
  { name: 'person', color: '#FF5733' },
  { name: 'car', color: '#3498DB' },
  { name: 'dog', color: '#2ECC71' },
] as const;

/**
 * Imágenes de ejemplo con storageKey fijo para mantener el seeder idempotente.
 */
const seedImages = [
  {
    filename: 'sample-red.png',
    storageKey: 'seed/sample-red.png',
    width: 320,
    height: 240,
    background: '#FF5733',
  },
  {
    filename: 'sample-blue.png',
    storageKey: 'seed/sample-blue.png',
    width: 320,
    height: 240,
    background: '#3498DB',
  },
] as const;

/**
 * Inserta o actualiza las categorías sin duplicarlas.
 */
async function seedCategoryData(): Promise<void> {
  for (const category of seedCategories) {
    const existing = await db
      .select({ id: categories.id })
      .from(categories)
      .where(eq(categories.name, category.name))
      .limit(1);

    if (existing.length === 0) {
      await db.insert(categories).values(category);
    } else {
      await db
        .update(categories)
        .set({ color: category.color })
        .where(eq(categories.name, category.name));
    }
  }
}

/**
 * Genera imágenes simples, las guarda en MinIO y registra sus metadatos.
 */
async function seedImageData(): Promise<void> {
  for (const image of seedImages) {
    const buffer = await sharp({
      create: {
        width: image.width,
        height: image.height,
        channels: 3,
        background: image.background,
      },
    })
      .png()
      .toBuffer();

    // putObject sobre la misma key reemplaza el objeto, no crea duplicados.
    await minioClient.putObject(minioBucket, image.storageKey, buffer, buffer.length, {
      'Content-Type': 'image/png',
    });

    const existing = await db
      .select({ id: images.id })
      .from(images)
      .where(eq(images.storageKey, image.storageKey))
      .limit(1);

    if (existing.length === 0) {
      await db.insert(images).values({
        filename: image.filename,
        storageKey: image.storageKey,
        mimeType: 'image/png',
        width: image.width,
        height: image.height,
        sizeBytes: buffer.length,
        status: 'pending',
      });
    }
  }
}

/**
 * Ejecuta el seeder completo.
 */
async function seed(): Promise<void> {
  await ensureMinioBucket();

  await seedCategoryData();
  await seedImageData();

  console.log('Seeder completado correctamente.');
}

seed()
  .catch((error: unknown) => {
    console.error('Error al ejecutar el seeder:', error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await pool.end();
  });
