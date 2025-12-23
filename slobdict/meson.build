configure_file(
  input: meson.project_name() + '.in',
  output: 'local-'+meson.project_name(),
  configuration: local_conf
)

configure_file(
  input:  meson.project_name() + '.in',
  output: meson.project_name(),
  configuration: conf,
  install_dir: get_option('bindir')
)

configure_file(
  input: 'constants.py.in',
  output: 'constants.py',
  configuration: conf,
  install: true,
  install_dir: PY_INSTALLDIR.get_install_dir() / meson.project_name(),
)

launcher = join_paths(meson.project_build_root(), meson.project_name(), 'local-' + meson.project_name())

run_target('run',
  command: [launcher]
)

# Install sources
py_sources = [
  '__init__.py',
  'app.py',
  'main.py',
  'search_provider.py',
]
PY_INSTALLDIR.install_sources(py_sources, subdir: meson.project_name() )

backend_modules = run_command(
  'find', 'backend', '-type', 'f', 
  check: true
).stdout().strip().split('\n')
PY_INSTALLDIR.install_sources(backend_modules, subdir: meson.project_name() + '/backend')

ui_modules = run_command(
  'find', 'ui', '-type', 'f', 
  check: true
).stdout().strip().split('\n')
PY_INSTALLDIR.install_sources(ui_modules, subdir: meson.project_name() + '/ui' )

utils_modules = run_command(
  'find', 'utils', '-type', 'f', 
  check: true
).stdout().strip().split('\n')
PY_INSTALLDIR.install_sources(utils_modules, subdir: meson.project_name() + '/utils' )
