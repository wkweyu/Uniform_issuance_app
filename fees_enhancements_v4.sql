-- v4: Individual Class Fee Structures and Enhanced Voteheads
ALTER TABLE `fee_structures` 
ADD COLUMN `class_id` INT DEFAULT NULL AFTER `term_id`,
DROP INDEX `unique_structure`,
ADD UNIQUE KEY `unique_structure_scope` (`academic_year_id`, `term_id`, `class_group_code`, `student_category`, `class_id`),
ADD CONSTRAINT `fk_structure_class` FOREIGN KEY (`class_id`) REFERENCES `classes`(`classID`);

ALTER TABLE `fee_voteheads`
ADD COLUMN IF NOT EXISTS `is_mandatory` BOOLEAN DEFAULT TRUE AFTER `priority`;

-- Update specific priorities for better distribution
UPDATE fee_voteheads SET priority = 1 WHERE name = 'Tuition';
UPDATE fee_voteheads SET priority = 2 WHERE name = 'Boarding';
UPDATE fee_voteheads SET priority = 3 WHERE name = 'Transport';
UPDATE fee_voteheads SET priority = 4 WHERE name = 'Admin Fees';
UPDATE fee_voteheads SET priority = 5 WHERE name = 'Caution Money';
UPDATE fee_voteheads SET priority = 10 WHERE name = 'Exam Fees';
UPDATE fee_voteheads SET priority = 11 WHERE name = 'Activity Fees';
UPDATE fee_voteheads SET priority = 12 WHERE name = 'Medical Fees';
UPDATE fee_voteheads SET priority = 13 WHERE name = 'Library';
UPDATE fee_voteheads SET priority = 14 WHERE name = 'Lab Fees';
UPDATE fee_voteheads SET priority = 15 WHERE name = 'P.T.A';
