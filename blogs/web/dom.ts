export function must<T extends Element>(root: ParentNode, selector: string, type: new () => T): T {
  const el = root.querySelector(selector);
  if (!(el instanceof type)) throw new Error(`expected a ${type.name} at ${selector}`);
  return el;
}

export function attr(el: Element, name: string): string {
  const value = el.getAttribute(name);
  if (value === null) throw new Error(`<${el.localName}> has no ${name} attribute`);
  return value;
}
