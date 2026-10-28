# Popup buttons

Every popup in `src/lib/popups/` places its actions the same way.

- **Where:** actions live in `PopupShell`'s `footer` snippet. A component that
  owns a popup's save logic hands its actions over through an
  `onfooterchange` prop, as the Operations tabs and `CollectionGroupSettings`
  do; it never renders them in the body.
- **Primary:** the one action the popup exists for is `btn-primary` (the
  accent) and sits last, on the right.
- **Dismiss:** Cancel or Close is `btn-secondary`, as in `ConfirmDialog`, just
  before the primary action.
- **Destructive or reset:** `btn-danger` for actions that remove something,
  `btn-secondary` for Reset; both take `footer-start`, which puts them on the
  left, apart from the rest.
- **Size:** footer buttons use the default size, never `btn-sm`.

Actions inside the body that act on one row or one section, such as a bulk
operation card's buttons, are not popup actions and keep their own placement.
