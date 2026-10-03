CREATE TABLE `training_jobs` (
  `id` bigint unsigned AUTO_INCREMENT NOT NULL,
  `status` enum('queued','running','completed','failed') NOT NULL DEFAULT 'queued',

  `optimizer` varchar(50) NOT NULL,
  `batch_size` int unsigned NOT NULL,
  `epochs` int unsigned NOT NULL,
  `learning_rate` double NOT NULL,
  `image_size` int unsigned NOT NULL,
  `dropout` double NOT NULL,

  `current_epoch` int unsigned NOT NULL DEFAULT 0,
  `progress` double NOT NULL DEFAULT 0,

  -- TEXT, no VARCHAR(16000): en utf8mb4 eso son 64 000 bytes y supera el límite de
  -- 65 535 bytes por fila de MariaDB (ERROR 1118 "Row size too large").
  `logs` text NOT NULL DEFAULT '',
  `error_message` varchar(2000),

  `created_at` timestamp NOT NULL DEFAULT (now()),
  `started_at` timestamp,
  `finished_at` timestamp,

  PRIMARY KEY (`id`)
);
--> statement-breakpoint

CREATE INDEX `training_jobs_status_idx`
ON `training_jobs` (`status`);
--> statement-breakpoint

CREATE INDEX `training_jobs_created_at_idx`
ON `training_jobs` (`created_at`);
