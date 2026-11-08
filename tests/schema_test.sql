-- TEST-ONLY schema, transcribed from the DDL in latest-schema-1.
-- Used by the test suite on a throwaway database whose name ends in _test.
-- Never run this against your real CourseRegistrationDB.
CREATE TABLE admin (
    admin_id integer NOT NULL PRIMARY KEY,
    name varchar(100) NOT NULL,
    email varchar(100) NOT NULL UNIQUE,
    password varchar(255) NOT NULL);
CREATE TABLE program (
    program_id integer NOT NULL PRIMARY KEY,
    program_name varchar(100) NOT NULL,
    program_type varchar(50) NOT NULL,
    duration_years integer NOT NULL);
CREATE TABLE department (
    department_id integer NOT NULL PRIMARY KEY,
    department_name varchar(100) NOT NULL,
    program_id integer NOT NULL REFERENCES program(program_id));
CREATE TABLE semester (
    semester_id integer NOT NULL PRIMARY KEY,
    program_id integer NOT NULL REFERENCES program(program_id),
    semester_number integer NOT NULL,
    academic_year_number integer NOT NULL,
    CONSTRAINT semester_program_id_semester_number_key UNIQUE (program_id, semester_number),
    CONSTRAINT semester_academic_year_number_check CHECK (academic_year_number > 0),
    CONSTRAINT semester_check CHECK (semester_number = 2*academic_year_number-1 OR semester_number = 2*academic_year_number));
CREATE TABLE student (
    student_id integer NOT NULL PRIMARY KEY,
    name varchar(100) NOT NULL,
    email varchar(100) NOT NULL UNIQUE,
    password_hash varchar(255) NOT NULL,
    program_id integer NOT NULL REFERENCES program(program_id),
    department_id integer NOT NULL REFERENCES department(department_id),
    current_semester_id integer NOT NULL REFERENCES semester(semester_id));
CREATE TABLE faculty (
    faculty_id integer NOT NULL PRIMARY KEY,
    name varchar(100) NOT NULL,
    email varchar(100) NOT NULL UNIQUE,
    password_hash varchar(255) NOT NULL);
CREATE TABLE course (
    course_id integer NOT NULL PRIMARY KEY,
    course_code varchar(30) NOT NULL UNIQUE,
    course_name varchar(150) NOT NULL,
    course_type varchar(20) NOT NULL,
    program_id integer NOT NULL REFERENCES program(program_id),
    department_id integer NOT NULL REFERENCES department(department_id),
    semester_id integer NOT NULL REFERENCES semester(semester_id),
    passing_mark numeric(5,2),
    CONSTRAINT course_course_type_check CHECK (course_type IN ('CORE','ELECTIVE')),
    CONSTRAINT course_passing_mark_check CHECK (passing_mark IS NULL OR (passing_mark >= 0 AND passing_mark <= 100)));
CREATE TABLE course_registration (
    registration_id integer NOT NULL PRIMARY KEY,
    student_id integer NOT NULL REFERENCES student(student_id),
    course_id integer NOT NULL REFERENCES course(course_id),
    semester_id integer NOT NULL REFERENCES semester(semester_id),
    registration_date date DEFAULT CURRENT_DATE NOT NULL,
    marks_obtained numeric(5,2),
    passing_mark_used numeric(5,2),
    result varchar(10) DEFAULT 'PENDING',
    registration_status varchar(15) DEFAULT 'REGISTERED' NOT NULL,
    CONSTRAINT course_registration_student_id_course_id_semester_id_key UNIQUE (student_id, course_id, semester_id),
    CONSTRAINT unique_registration_student UNIQUE (registration_id, student_id),
    CONSTRAINT course_registration_check CHECK (result = 'PENDING' OR (marks_obtained IS NOT NULL AND passing_mark_used IS NOT NULL)),
    CONSTRAINT course_registration_marks_obtained_check CHECK (marks_obtained IS NULL OR (marks_obtained >= 0 AND marks_obtained <= 100)),
    CONSTRAINT course_registration_passing_mark_used_check CHECK (passing_mark_used IS NULL OR (passing_mark_used >= 0 AND passing_mark_used <= 100)),
    CONSTRAINT course_registration_registration_status_check CHECK (registration_status IN ('REGISTERED','COMPLETED','CANCELLED')),
    CONSTRAINT course_registration_result_check CHECK (result IN ('PENDING','PASS','FAIL')));
CREATE TABLE faculty_assignment (
    assignment_id integer NOT NULL PRIMARY KEY,
    faculty_id integer NOT NULL REFERENCES faculty(faculty_id),
    program_id integer REFERENCES program(program_id),
    department_id integer REFERENCES department(department_id),
    semester_id integer REFERENCES semester(semester_id),
    course_id integer REFERENCES course(course_id),
    student_id integer REFERENCES student(student_id),
    registration_id integer,
    CONSTRAINT fk_faculty_assignment_registration FOREIGN KEY (registration_id) REFERENCES course_registration(registration_id),
    CONSTRAINT fk_assignment_registration_student FOREIGN KEY (registration_id, student_id) REFERENCES course_registration(registration_id, student_id),
    CONSTRAINT chk_faculty_assignment_type CHECK (
        (student_id IS NULL AND registration_id IS NULL AND program_id IS NOT NULL AND department_id IS NOT NULL AND semester_id IS NOT NULL AND course_id IS NOT NULL)
        OR (student_id IS NOT NULL AND registration_id IS NOT NULL AND program_id IS NOT NULL AND department_id IS NOT NULL AND semester_id IS NOT NULL AND course_id IS NOT NULL)));
CREATE INDEX index_assignment_faculty ON faculty_assignment (faculty_id);
CREATE INDEX index_registration_course ON course_registration (course_id);
CREATE INDEX index_registration_student ON course_registration (student_id);
CREATE UNIQUE INDEX unique_faculty_course ON faculty_assignment (faculty_id, course_id) WHERE student_id IS NULL;
CREATE UNIQUE INDEX unique_faculty_student_registration ON faculty_assignment (faculty_id, registration_id) WHERE registration_id IS NOT NULL;
CREATE TABLE passing_mark_approval (
    approval_id integer NOT NULL PRIMARY KEY,
    course_id integer NOT NULL REFERENCES course(course_id),
    proposed_passing_mark numeric(5,2) NOT NULL,
    faculty_id integer REFERENCES faculty(faculty_id),
    admin_id integer REFERENCES admin(admin_id),
    faculty_status varchar(10) DEFAULT 'PENDING' NOT NULL,
    admin_status varchar(10) DEFAULT 'PENDING' NOT NULL,
    approval_date date,
    CONSTRAINT passing_mark_approval_admin_status_check CHECK (admin_status IN ('PENDING','APPROVED','REJECTED')),
    CONSTRAINT passing_mark_approval_faculty_status_check CHECK (faculty_status IN ('PENDING','APPROVED','REJECTED')),
    CONSTRAINT passing_mark_approval_proposed_passing_mark_check CHECK (proposed_passing_mark >= 0 AND proposed_passing_mark <= 100));
CREATE INDEX index_approval_course ON passing_mark_approval (course_id);
