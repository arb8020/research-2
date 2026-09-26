/**
 * SQL literal quoting. One implementation, two callers.
 *
 * Both the panel builder (metric names, file names) and the server's read-only
 * gate (`json_serialize_sql(<the query text>)`, the runs glob) need to put a
 * runtime string inside a SQL single-quoted literal, and had their own copy.
 * Two copies of an escaping rule is one copy too many: the day one of them
 * learns about a new escape and the other does not is the day an injection
 * lands in whichever was forgotten.
 */

/**
 * A DuckDB single-quoted string literal.
 *
 * Doubling the quote is sufficient ONLY because DuckDB's single-quoted strings
 * have no backslash escape sequences: `'\\'` is a literal backslash, not an
 * escaped quote, so there is no way to smuggle a quote back out. In a dialect
 * with C-style escapes (MySQL's default, Postgres' E'' strings) this function
 * would be an injection.
 */
export function sqlLiteral(value: string): string {
  return `'${value.replaceAll("'", "''")}'`;
}
