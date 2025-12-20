gnome = import('gnome')

subdir('ui')

configure_file(
  input: '@0@.gresource.xml.in'.format(meson.project_name()),
  output: '@0@.gresource.xml'.format(meson.project_name()),
  configuration: conf,
)

configure_file(
  input: '@0@.metainfo.xml.in'.format(meson.project_name()),
  output: '@0@.metainfo.xml'.format(APPLICATION_ID),
  configuration: conf,
  install: true,
  install_dir: join_paths(get_option('datadir'), 'metainfo')
)

configure_file(
  input: '@0@.desktop.in'.format(meson.project_name()),
  output: '@0@.desktop'.format(APPLICATION_ID),
  configuration: conf,
  install: true,
  install_dir: join_paths(get_option('datadir'), 'applications')
)

gnome.compile_resources(meson.project_name(),
  join_paths(meson.current_build_dir(), meson.project_name()+'.gresource.xml'),
  gresource_bundle: true,
  source_dir: meson.current_build_dir(),
  install: true,
  install_dir: PKGDATA_DIR,
  dependencies: blueprints
)

configure_file(
  input: '@0@.gschema.xml.in'.format(meson.project_name()),
  output: '@0@.gschema.xml'.format(APPLICATION_ID),
  configuration: conf,
  install: true,
  install_dir: join_paths(get_option('datadir'), 'glib-2.0/schemas')
)

compile_schemas = find_program('glib-compile-schemas', required: false)
if compile_schemas.found()
  test('Validate schema file', compile_schemas,
    args: ['--strict', '--dry-run', meson.current_source_dir()]
  )
endif

subdir('icons')
