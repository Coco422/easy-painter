ALTER TABLE model_configs ADD COLUMN max_reference_images INTEGER NOT NULL DEFAULT 5
    CHECK (max_reference_images >= 1);
ALTER TABLE generation_jobs ADD COLUMN reference_images JSON;
