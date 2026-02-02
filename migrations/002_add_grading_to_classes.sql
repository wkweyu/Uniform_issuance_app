ALTER TABLE classes ADD COLUMN grading_scale_id INT DEFAULT NULL;
ALTER TABLE classes ADD CONSTRAINT fk_class_grading_scale FOREIGN KEY (grading_scale_id) REFERENCES grading_scales(id) ON DELETE SET NULL;
