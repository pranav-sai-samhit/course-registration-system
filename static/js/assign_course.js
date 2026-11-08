// Cascading selects for course-level assignment: program -> department / year -> semester -> course.
// The server re-validates every combination; this only narrows the choices for convenience.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var program = $('a-program'), department = $('a-department'), year = $('a-year'),
      semester = $('a-semester'), course = $('a-course');
  if (!program || !course) { return; }

  function narrow(select, test) {
    var current = select.value;
    Array.prototype.forEach.call(select.options, function (option) {
      if (!option.value) { return; }
      var ok = test(option.dataset);
      option.hidden = !ok;
      option.disabled = !ok;
    });
    var selected = select.options[select.selectedIndex];
    if (current && selected && selected.disabled) { select.value = ''; }
  }

  function refresh() {
    narrow(department, function (d) { return !program.value || d.program === program.value; });
    narrow(year, function (d) { return !program.value || d.program === program.value; });
    narrow(semester, function (d) {
      return (!program.value || d.program === program.value) && (!year.value || d.year === year.value);
    });
    narrow(course, function (d) {
      return (!program.value || d.program === program.value) &&
             (!department.value || d.department === department.value) &&
             (!semester.value || d.semester === semester.value);
    });
  }
  [program, department, year, semester].forEach(function (el) { el.addEventListener('change', refresh); });
  refresh();
})();
