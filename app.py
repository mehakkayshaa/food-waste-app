import streamlit as st
import pandas as pd

# Set up the page UI
st.set_page_config(page_title="EcoBite - AI Food Saver", page_icon="🌱", layout="centered")

# --- INITIALIZE SESSION STATE ---
# This acts as our app's memory so the fridge inventory doesn't erase when we switch tabs
if 'inventory' not in st.session_state:
    st.session_state['inventory'] = pd.DataFrame(columns=['Item', 'Days Usable', 'Carbon Footprint (kg CO2e)'])

st.title("🌱 EcoBite: AI Food Waste Manager")
st.markdown("Automated inventory, predictive spoilage, and carbon tracking for a greener kitchen.")

# Create navigation tabs
tab1, tab2, tab3 = st.tabs(["📸 1. AI Scanner", "⚠️ 2. Smart Alerts & 3. Recipes", "🌍 4. Carbon Tracker"])

# --- TAB 1: AI GROCERY SCANNER ---
with tab1:
    st.header("📸 AI Grocery Scanner")
    st.write("Scan your receipt or take a photo of your groceries. The AI will log the items and predict their spoilage window.")
    
    camera = st.camera_input("Take a picture of your food")
    
    if camera is not None:
        with st.spinner("AI Vision Model analyzing image..."):
            import time
            time.sleep(2) # Simulating the AI processing time
            
            # Simulated AI output based on Poore and Nemecek (2018) data
            new_data = pd.DataFrame({
                'Item': ['Beef (1kg)', 'Tomatoes (1kg)', 'Bread (1 loaf)'],
                'Days Usable': [3, 5, 7],
                'Carbon Footprint (kg CO2e)': [99.48, 2.09, 0.50]
            })
            st.session_state['inventory'] = pd.concat([st.session_state['inventory'], new_data], ignore_index=True)
            
        st.success("✅ AI identified: Beef, Tomatoes, and Bread!")
        st.dataframe(new_data)

# --- TAB 2: SMART ALERTS & RECIPE RESCUE ---
with tab2:
    st.header("⚠️ Smart Alerts")
    st.write("Your active inventory, prioritized by spoilage prediction:")
    
    if not st.session_state['inventory'].empty:
        # Sort inventory so items spoiling soonest are at the top
        df = st.session_state['inventory'].sort_values('Days Usable')
        st.dataframe(df)
        
        st.divider()
        
        st.header("🍲 AI Recipe Rescue")
        st.write("Here are recipes specifically generated to use up your at-risk ingredients.")
        
        # Check if beef or tomatoes are in the inventory for the demo
        urgent_items = df[df['Days Usable'] <= 3]['Item'].tolist()
        
        st.info("**Chef's Special: Hearty Beef & Tomato Stew**\n\n*Uses your at-risk Beef (3 days left) and Tomatoes (5 days left)!*")
        
        if st.button("I cooked this! (Log Meal & Rescue Food)"):
            st.success("Meal logged! You successfully rescued this food from the bin.")
            st.balloons()
    else:
        st.info("Your inventory is empty. Use the AI Scanner to add groceries!")

# --- TAB 3: CARBON IMPACT TRACKER ---
with tab3:
    st.header("🌍 Carbon Impact Tracker")
    st.write("Track the exact greenhouse gas emissions you prevent by eating your food before it spoils.")
    
    # Hardcoded demo metric for the presentation
    st.metric(
        label="Total CO₂ Equivalent Saved", 
        value="101.57 kg", 
        delta="Equivalent to driving a gas car for 260 miles!"
    )
    
    st.write("**The Math:** Based on the Poore and Nemecek (2018) global supply chain data. Saving 1kg of beef prevents ~99.48 kg of CO₂e from being wasted.")
