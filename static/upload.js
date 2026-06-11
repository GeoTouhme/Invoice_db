/* Drag & drop file picker + busy state on submit, shared by both upload pages.
 *
 * initUploadForm({
 *   formId:     id of the <form>
 *   inputId:    id of the hidden <input type="file">
 *   zoneId:     id of the dropzone element
 *   nameId:     id of the element that shows the chosen filename
 *   submitId:   id of the submit button
 *   busyLabel:  button text while submitting
 *   extension:  required filename extension, e.g. ".csv"
 * })
 */
function initUploadForm(opts) {
  const form = document.getElementById(opts.formId);
  const input = document.getElementById(opts.inputId);
  const zone = document.getElementById(opts.zoneId);
  const nameEl = document.getElementById(opts.nameId);
  const submit = document.getElementById(opts.submitId);

  function showFile() {
    if (input.files.length) {
      nameEl.textContent = '✓ ' + input.files[0].name;
      nameEl.classList.remove('d-none');
      zone.classList.add('has-file');
    }
  }

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', showFile);

  ['dragenter', 'dragover'].forEach((evt) =>
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.classList.add('dragover');
    })
  );
  ['dragleave', 'drop'].forEach((evt) =>
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      if (evt === 'dragleave' && zone.contains(e.relatedTarget)) return;
      zone.classList.remove('dragover');
    })
  );
  zone.addEventListener('drop', (e) => {
    const files = e.dataTransfer.files;
    if (!files.length) return;
    if (!files[0].name.toLowerCase().endsWith(opts.extension)) {
      nameEl.textContent = '✗ Only ' + opts.extension + ' files are allowed';
      nameEl.classList.remove('d-none');
      return;
    }
    const dt = new DataTransfer();
    dt.items.add(files[0]);
    input.files = dt.files;
    showFile();
  });

  form.addEventListener('submit', (e) => {
    if (!input.files.length) {
      e.preventDefault();
      nameEl.textContent = '✗ Choose a file first';
      nameEl.classList.remove('d-none');
      return;
    }
    submit.disabled = true;
    submit.innerHTML =
      '<span class="spinner-border spinner-border-sm me-2" role="status"></span>' +
      opts.busyLabel;
  });
}
