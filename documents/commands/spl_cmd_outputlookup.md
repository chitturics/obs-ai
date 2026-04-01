---
 command: outputlookup
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/outputlookup
 title: outputlookup
 download_date: 2026-02-03 09:13:19
---

 # outputlookup

Writes search results to a static lookup table, or KV store collection, that you specify.

CAUTION: This command is considered risky because, if used incorrectly, it can pose a security risk or potentially lose data when it runs. As a result, this command triggers SPL safeguards. See SPL safeguards for risky commands in Securing the Splunk Platform.

The required syntax is in bold.

#### Required arguments

You must specify one of the following required arguments, either filename or tablename.

#### Optional arguments

The lookup table must be a CSV or GZ file, or a table name specified with a lookup table configuration in transforms.conf. The lookup table can refer to a KV store collection or a CSV lookup.  The outputlookup command cannot be used with external lookups.

If you specify a lookup table file name with the .gz extension, the file that's created is compressed.

#### Determine where the lookup table file is created

For CSV lookups, outputlookup creates a lookup table file for the results of the search. There are three locations where outputlookup can put the file it creates:

- The system lookups directory: $SPLUNK_HOME/etc/system/local/lookups
- The lookups directory for the current app context: $SPLUNK_HOME/etc/apps/<app>/lookups
- The app-based lookups directory for the user running the search: etc/users/<user>/<app>/lookups

You can use the createinapp or create_context arguments to determine where outputlookup creates the lookup table for a given search. If you try to use both of these arguments in the same search, createinapp argument overrides the create_context argument.

If you do not use either argument in your search, the create_context setting in limits.conf determines where outputlookup creates the lookup table file. This setting defaults to app if there is an app context when you run the search, or to system, if there is not an app context when you run the search.

To have outputlookup create the lookup table file in the system lookups directory, set createinapp=false or set create_context=system. Alternatively, if you do not have an app context when you run the search, leave both arguments out of the search and rely on the limits.conf version of create_context to put the lookup table file in the system directory. This last approach only works if the create_context setting in limits.conf has not been set to user.

To have outputlookup create the lookup table file in the lookups directory for the current app context, set createinapp=true or set create_context=app. Alternatively, if you do have an app context when you run the search, leave both arguments out of the search and rely on the limits.conf version of create_context to put the lookup table file in the app directory. This last approach only works if the create_context setting in limits.conf has not been set to user.

To have outputlookup create the lookup table file in the lookups directory for the user running the search, set create_context=user. Alternatively, if you want all outputlookup searches to create lookup table files in user lookup directories by default, you can set create_context=user in limits.conf. The createinapp and create_context arguments can override this setting if they are used in the search.

Note: If the lookup table file already exists in the location to which it is written, the existing version of the file is overwritten with the results of the outputlookup search.

#### Restrict write access to lookup table files with check_permission

For permissions in CSV lookups, use the check_permission field in transforms.conf and outputlookup_check_permission in limits.conf to restrict write access to users with the appropriate permissions when using the outputlookup command. Both check_permission and outputlookup_check_permission default to false. Set to true for Splunk software to verify permission settings for lookups for users. You can change lookup table file permissions in the .meta file for each lookup file, or Settings > Lookups > Lookup table files. By default, only users who have the admin or power role can write to a shared CSV lookup file.

For more information about creating lookups, see About lookups in the Knowledge Manager Manual.

For more information about App Key Value Store collections, see  About KV store in the Admin Manual.

#### Append results

Suppose you have an existing CSV file that contains fields A, D, and J. The results of your search are fields A, C, and J. If you run a search with outputlookup append=false, then fields A, C, and J are written to the CSV file. Field D is not retained.

If you run a search with outputlookup append=true, then only the fields that are currently in the file are preserved. In this example, fields A and J are written to the CSV file. Field C is lost because it does not already exist in the CSV file. Field D is retained.

You can work around this issue by using the eval command to add a field to your CSV file before you run the search. For example, if your CSV file is named users, you would do something like this:

Then run your search and pipe the results to the fields command for the fields in the file that you want to preserve.

#### Multivalued fields

When you output to a static lookup table, the outputlookup command merges values in a multivalued field into single space-delimited value.  This does not apply to a KV store collection.

#### 1. Write to a lookup table using settings in the transforms.conf file

Write to usertogroup lookup table as specified in the transforms.conf file.

#### 2. Write to a lookup file in a specific system or app directory

Write to users.csv lookup file under $SPLUNK_HOME/etc/system/lookups or $SPLUNK_HOME/etc/apps/*/lookups.

#### 3. Specify not to override the lookup file if no results are returned

Write to users.csv lookup file, if results are returned, under $SPLUNK_HOME/etc/system/lookups or $SPLUNK_HOME/etc/apps/*/lookups. Do not delete the users.csv file if no results are returned.

#### 4. Write to a KV store collection

Write food inspection events for Shalimar Restaurant to a KV store collection called kvstorecoll. This collection is referenced in a lookup table called kvstorecoll_lookup.

#### 5. Overwrite KV store collections

By default, append is set to true when the key_field is used with the outputlookup command. If you don't want to append search results to an existing KV store collection, you can override the default behavior by directly setting key_field with append=false.

For example, in the following outputlookup search, the KV store called accounts is appended. This is because key_field sets append=true by default.

However, in the following outputlookup search, the KV store called accounts is overwritten because append=false. In this case, the append subsearch runs before the main search, which empties the entire KV store before the fields are written to accounts.

Alternatively, if you want your entire lookup to reflect your search results and you don't mind using the default system-generated keys, eliminate key_field=key from your outputlookup search, like this.

#### 6. Write from a CSV file to a KV store collection

Write the contents of a CSV file to the KV store collection kvstorecoll using the lookup table kvstorecoll_lookup. This requires usage of both inputlookup and outputlookup commands.

#### 7. Update field values for a single KV store collection record

Update field values for a single KV store collection record. This requires you to use the inputlookup, outputlookup, and eval commands. The record is indicated by the value of its internal key ID (the _key field) and is updated with a new customer name and customer city. The record belongs to the KV store collection kvstorecoll, which is accessed through the lookup table kvstorecoll_lookup.

To learn how to obtain the internal key ID values of the records in a KV store collection, see Example 5 for the inputlookup command.
 