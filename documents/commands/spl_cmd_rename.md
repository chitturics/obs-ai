---
 command: rename
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/rename
 title: rename
 download_date: 2026-02-03 09:15:09
---

 # rename

Use the rename command to rename one or more fields. This command is useful for giving fields more meaningful names, such as "Product ID" instead of "pid". If you want to rename fields with similar names, you can use a wildcard character.
See the Usage section.

rename <wc-field> AS <wc-field>...

#### Required arguments

The rename command is a distributable streaming command. See Command types.

#### Rename with a phrase

Use quotation marks when you rename a field with a phrase.

#### Rename multiple, similarly named fields

Use wildcards to rename multiple fields with similar names. For example, suppose you have the following field names:

- EU_UK
- EU_DE
- EU_PL

You can rename the fields to replace EU with EMEA:

The results show these field names:

- EMEA_UK
- EMEA_DE
- EMEA_PL

Both the original and renamed fields must include the same number of wildcards, otherwise a wildcard mismatch error is returned. See Examples.

#### You can't rename one field with multiple names

You can't rename one field with multiple names. For example if you have field A, you can't specify | rename A as B, A as C.  This rule also applies to other commands where you can rename fields, such as the stats command.

The following example is not valid:

#### You can't merge multiple fields into one field

You can't use the rename command to merge multiple fields into one field because null, or non-present, fields are brought along with the values.

For example, if you have events with either product_id or pid fields, ... | rename pid AS product_id would not merge the pid values into the product_id field. It overwrites product_id with Null values where pid does not exist for the event. See the eval command and coalesce() function.

#### You can't match wildcard characters while renaming fields

You can use the asterisk ( * ) in your searches as a wildcard character, but you can't use a backslash ( \ ) to escape an asterisk in search strings. A backslash \ and an asterisk * match the characters \* in searches, not an escaped wildcard character. Because the Splunk platform doesn't support escaping wildcards, asterisk ( * ) characters in field names in rename searches can't be matched and replaced.

#### Renaming a field that does not exist

Renaming a field can cause loss of data.

Suppose you rename fieldA to fieldB, but fieldA does not exist.

- If fieldB does not exist, nothing happens.
- If fieldB does exist, the result of the rename is that the data in fieldB is removed. The data in fieldB will contain null values.

#### The original and new field names must have the same number of wildcards

The number of asterisks ( * ) in the original name must match the number of asterisks in the new name. For example, the following search fails because there is one wildcard character in the original name, but none in the name that replaces it:

The following search completes successfully because the number of wildcard characters in both names is the same.

#### Support for backslash characters ( \ ) in the rename command

To match a backslash character ( \ ) in a field name when using the rename command, use 2 backslashes for each backslash in the original field name. For example, to rename the field name http\\:8000 to localhost:8000, use the following command in your search:

See Backslashes in the Search Manual.

#### 1. Rename a single field

Rename the "_ip" field to "IPAddress".

#### 2. Rename fields with similar names using a wildcard

Rename fields that begin with "usr" to begin with "user".

#### 3. Specifying a field name that contains spaces

Rename the "count" field. Names with spaces must be enclosed in quotation marks.
 