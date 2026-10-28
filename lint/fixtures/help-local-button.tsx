// This file declares its own Button and never imports the kit's, so the tag is not the kit's and UI011
// and UI012 leave it alone.
function Button({ disabled, children }: { disabled?: boolean; children?: unknown }) {
  return <span aria-disabled={disabled}>{children as string}</span>;
}

export function Local() {
  return <Button disabled>Own component</Button>;
}
