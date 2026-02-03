-- 📦 Essential System Tables
-- Extract structure for `users` (based on backup)
CREATE TABLE IF NOT EXISTS `users` (
  `userNo` int(11) NOT NULL AUTO_INCREMENT,
  `StaffID` varchar(6) DEFAULT NULL,
  `username` varchar(32) UNIQUE NOT NULL,
  `pwd` varchar(255) DEFAULT '123456',
  `domainID` int(11) DEFAULT NULL,
  `access_flag` tinyint(4) DEFAULT 1,
  `dateReg` varchar(32) DEFAULT NULL,
  `RegStaffID` varchar(6) DEFAULT NULL,
  `TA` int(1) DEFAULT 0,
  `_date` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`userNo`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- 📦 Academic and Enrollment Tables (Standardized)
CREATE TABLE IF NOT EXISTS `studentinfo` (
  `AdmNo` varchar(20) NOT NULL,
  `FName` varchar(255) DEFAULT NULL,
  `LName` varchar(255) DEFAULT NULL,
  `DOB` date DEFAULT NULL,
  `Gender` varchar(10) DEFAULT NULL,
  PRIMARY KEY (`AdmNo`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

CREATE TABLE IF NOT EXISTS `classes` (
  `classID` int(11) NOT NULL AUTO_INCREMENT,
  `class_name` varchar(50) NOT NULL,
  `class_group` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`classID`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

CREATE TABLE IF NOT EXISTS `classallocation` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `AdmNo` varchar(20) DEFAULT NULL,
  `classID` int(11) DEFAULT NULL,
  `thisYear` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `AdmNo` (`AdmNo`),
  KEY `classID` (`classID`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- 📦 Ensure we have at least one term date record (otherwise app shows warnings)
INSERT IGNORE INTO `uniform_term_dates` (`term_number`, `year`, `start_date`, `end_date`)
VALUES (1, 2026, '2026-01-01', '2026-04-30');
