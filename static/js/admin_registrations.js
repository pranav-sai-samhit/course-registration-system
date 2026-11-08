// Pre-select the registration semester from the chosen student's current semester.
(function () {
  var student = document.getElementById('r-student');
  var semester = document.getElementById('r-semester');
  if (!student || !semester) { return; }
  student.addEventListener('change', function () {
    var option = student.options[student.selectedIndex];
    if (option && option.dataset.semesterId) { semester.value = option.dataset.semesterId; }
  });
})();
