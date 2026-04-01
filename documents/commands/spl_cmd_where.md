---
 command: where
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/where
 title: where
 download_date: 2026-02-03 09:21:02
---

 # where

The where command uses eval-expressions to filter search results. These eval-expressions must be Boolean expressions, where the expression returns either true or false. The where command returns only the results for which the eval expression returns true.

where <eval-expression>

#### Required arguments

The where command is a distributable streaming command. See Command types.

The <eval-expression> is case-sensitive.

The where command uses the same expression syntax as the eval command. Also, both commands interpret quoted strings as literals. If the string is not quoted, it is treated as a field name. Because of this, you can use the where command to compare two different fields, which you cannot use the search command to do.

| Command | Example | Description |
| --- | --- | --- |
| Where | ... | where ipaddress=clientip | This search looks for events where the field ipaddress is equal to the field clientip. |
| Search | | search host=www2 | This search looks for events where the field host contains the string value www2. |
| Where | ... | where host="www2" | This search looks for events where the value in the field host is the string value www2. |

#### Boolean expressions

The order in which Boolean expressions are evaluated with the where command is:

- Expressions within parentheses
- NOT clauses
- AND clauses
- OR clauses
- XOR clauses

This evaluation order is different than the order used with the search command, which evaluates OR before AND clauses, and doesn't support XOR.

See Boolean expressions with logical operators in the Splunk platform Search Manual.

#### Using a wildcard with the where command

You can only specify a wildcard by using the like function with the where command. The percent ( % ) symbol is the wildcard that you use with the like function.  See the like() evaluation function.

#### Supported functions

You can use a wide range of evaluation functions with the where command. For general information about using functions, see Evaluation functions.

- For a list of functions by category, see Function list by category.
- For an alphabetical list of functions, see Alphabetical list of functions.

#### 1. Specify a wildcard with the where command

You can only specify a wildcard with the where command by using the like function. The percent ( % ) symbol is the wildcard you must use with the like function. The where command returns like=TRUE if the ipaddress field starts with the value 198..

#### 2. Match IP addresses or a subnet using the where command

Return "CheckPoint" events that match the IP or is in the specified subnet.

#### 3. Specify a calculation in the where command expression

Return "physicsjobs" events with a speed is greater than 100.

eval, search, regex
 