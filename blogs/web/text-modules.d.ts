// Files esbuild bundles as text (--loader:.py=text in package.json): the import is the file's contents.
declare module "*.py" {
  const text: string;
  export default text;
}
