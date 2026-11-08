// Bootstrap client-side validation for forms marked .needs-validation
document.querySelectorAll('form.needs-validation').forEach(function (form) {
  form.addEventListener('submit', function (event) {
    if (!form.checkValidity()) { event.preventDefault(); event.stopPropagation(); }
    form.classList.add('was-validated');
  });
});

// Confirmation before destructive actions: <form data-confirm="Delete this record?">
document.querySelectorAll('form[data-confirm]').forEach(function (form) {
  form.addEventListener('submit', function (event) {
    if (!window.confirm(form.dataset.confirm)) { event.preventDefault(); }
  });
});

// Live filter for tables: <input data-table-filter="#table-id">
document.querySelectorAll('input[data-table-filter]').forEach(function (input) {
  var table = document.querySelector(input.dataset.tableFilter);
  if (!table) { return; }
  input.addEventListener('input', function () {
    var needle = input.value.trim().toLowerCase();
    table.querySelectorAll('tbody tr').forEach(function (row) {
      row.hidden = needle !== '' && row.textContent.toLowerCase().indexOf(needle) === -1;
    });
  });
});
