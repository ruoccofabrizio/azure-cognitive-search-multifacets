import streamlit as st
import pandas as pd
from urllib.error import URLError
import requests
from pprint import pprint
import os
from collections import Counter
from copy import copy

os.environ['search_service'] = ''
os.environ['index_name'] = 'multifacets'
os.environ['api_version'] = '2021-04-30-Preview'
os.environ['api_key'] = ''
os.environ['facets'] = 'brand,vendor,category'
top = 1000

# Function called when pushing on a filter button in the UI
def push_filter(checkbox_key):
    # Get facet and value from filter
    facet = checkbox_key.split('$')[1]
    value = checkbox_key.split('$')[2].split('#')[0]
    count = checkbox_key.split('$')[2].split('#')[1]

    # if facet is not in active filters add the filter
    if facet not in list(map(lambda x: x['facet'], st.session_state['filters'])):
        st.session_state['filters'].append({"facet": facet, "value": [value], "count": int(count)})
    else:
        # if the facet is already in the active filter, retrieve the item in the filter list
        filt = list(filter(lambda x: x['facet'] == facet, st.session_state['filters']))[0]
        # if the value for the facet is already in the active filters, remove it (this happens when in the UI you deselect the filter)
        if value in filt['value']:
            filt['value'].remove(value)
            # if all the values for the specific facet are removed, remove the filter as well from the active filters
            if filt['value'] == []:
                st.session_state['filters'] = list(filter(lambda x: x['facet'] != facet, st.session_state['filters']))
        # if the value is not in the active filters list, add it
        else:
            filt['value'].append(value)

# Send query to Azure Cognitive Search
def send_query(search= "*"):
    # Evalute if you need to issue a new query to Search Engine or work with session data 
    # Here you can also add considerations on the number of items in the result to issue other queries for faceting if needed
    if st.session_state['local_query']['query'] != search:
        # Search URL
        url = f"https://{os.environ['search_service']}.search.windows.net/indexes/{os.environ['index_name']}/docs/search?api-version={os.environ['api_version']}"
        # Required authentication headers
        headers = {
            "content-type" : "application/json",
            "api-key" : os.getenv('api_key')
        }
        # Compute facet with Azure Cognitive Search format
        facets = {x : f"{x},count:50" for x in os.environ['facets'].replace(' ','').split(',')}
        facets = [v for k,v in facets.items()]

        # Store the search query in the Session Store
        st.session_state['local_query']['query'] = search

        # Create the request body
        body = {
            "search" : search,
            "facets" : facets,
            "queryType" : "full",
            "count" : True,
            "top": top
        }
        # Log request body for debugging
        pprint(body)
        # Send request to Azure Cognitive Search
        r = requests.post(url, headers=headers, json=body)
        # Log request status code
        print(r.status_code)
        # Print an error if request fails
        if not r.ok:
            r.text

        # Update Session results with data coming from Azure Cognitive Search
        st.session_state['local_query']['results'] = r.json()
        res = r.json()
            
    else:
        res = copy(st.session_state['local_query']['results'])        
        results = copy(st.session_state['local_query']['results'])['value']
        
        # Apply active filters on the result set
        for f in st.session_state['filters']:
            results = list(filter(lambda x: x[f['facet']] in f['value'], results))

        # Overwrite new results, facets and result lenght for visualization
        res['value'] = results
        res['@search.facets'] = compute_facets()
        res['@odata.count'] = len(results)
        
    return res

# Locally compute the search facets
def compute_facets():
    search_facets = {}
    search_facets_output = {}
    facets = os.environ['facets'].replace(' ','').split(',')
    # For each facet count the docs applying all filters but those on the facet itself, starting from the full result set
    for facet in facets:
        search_facets[facet] = copy(st.session_state['local_query']['results'])['value']
        for f in st.session_state['filters']:
            if f['facet'] != facet: # Exclude the filter on the facet you are computing the counter
                search_facets[facet] = list(filter(lambda x: x[f['facet']] in f['value'] , search_facets[facet]))
        # Count all the values and re-format in the ['@search.facets'] format
        search_facets_output[facet] = []
        for k,v in Counter(list(map(lambda x: x[facet], search_facets[facet]))).items():
            search_facets_output[facet].append({"count": v, "value": k})
        search_facets_output[facet] = sorted(search_facets_output[facet], key= lambda x: x['count'], reverse=True)
    return search_facets_output
        

# Add facet on the sidebar
def add_facet(facet):
    # Write facet name
    st.sidebar.write(facet.capitalize())
    # Read facet value from the last query if available
    facet_values = []
    if r.get('@search.facets') != None and r.get('@search.facets').get(facet) != None:
        facet_values = r.get('@search.facets').get(facet)

    # Extract all the filter already active in the UI for rendering them as selected
    active_filters = list(filter(None,map(lambda x: x['value'] if x['facet'] == facet else None, st.session_state['filters'])))
    active_filters = active_filters[0] if len(active_filters) > 0 else []
    # Draw all the facet buttons in the UI and define the callback function
    for f in facet_values:
        st.sidebar.checkbox(f['value'] + ' (' + str(f['count']) +')' ,
            on_change=push_filter, 
            value= True if f['value'] in active_filters else False,
            kwargs={"checkbox_key" : f"facet${facet}${f['value']}#{f['count']}"}
            )

# MAIN 
try:
    # Define search bar and default search value
    default = "jeans"
    search = st.text_input("Search Query", default)

    # Create a Session variable collecting applied filters
    if "filters" not in st.session_state:
        st.session_state['filters'] = []  
    # Create a Session variable to use local data when the query does not change
    if "local_query" not in st.session_state:
        st.session_state['local_query'] = {
            "query": "",
            "results": {}
        }

    # Send Query to Azure Cognitive Search
    r = send_query(search=search)
    # Add facets for configured fields
    for f in os.environ['facets'].replace(' ','').split(','):
        add_facet(f)

    # Show query results and count
    st.write(f"Results count: {r['@odata.count']}")
    search_res = pd.DataFrame(r['value'])
    search_res.index = search_res.index +1 # Just for visualization re-index the Pandas dataframe
    search_res

except URLError as e:
    st.error(
        """
        **This demo requires internet access.**

        Connection error: %s
        """
        % e.reason
    )

