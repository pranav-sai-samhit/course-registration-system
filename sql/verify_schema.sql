-- READ-ONLY checks. Run in pgAdmin against CourseRegistrationDB. Changes nothing.
-- 1) exactly the ten tables
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1;
-- 2) the objects this application relies on (each row should say present = true)
SELECT 'chk_faculty_assignment_type' AS object,
       EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_faculty_assignment_type') AS present
UNION ALL SELECT 'fk_assignment_registration_student',
       EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_assignment_registration_student')
UNION ALL SELECT 'unique_registration_student',
       EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'unique_registration_student')
UNION ALL SELECT 'unique_faculty_course', EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'unique_faculty_course')
UNION ALL SELECT 'unique_faculty_student_registration',
       EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'unique_faculty_student_registration');
-- 3) nullable columns the workflow needs (is_nullable should be YES)
SELECT table_name, column_name, is_nullable FROM information_schema.columns
WHERE table_schema = 'public' AND (table_name, column_name) IN
  (('course','passing_mark'), ('course_registration','passing_mark_used'),
   ('passing_mark_approval','faculty_id'), ('passing_mark_approval','admin_id'));
