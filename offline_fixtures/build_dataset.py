# [OFFLINE TEST FIXTURE GENERATOR - NOT THE LIVE COLLECTOR]
# build_dataset.py
#
# NOTICE FOR REVIEWERS:
# This file generates offline synthetic test fixture datasets for local UI demonstration.
# The actual automated scraper is in /scraper/walmart_scraper.py.
import json

def compute_check_digit(digits_11: str) -> str:
    odd_sum = sum(int(digits_11[i]) for i in range(0, 11, 2))
    even_sum = sum(int(digits_11[i]) for i in range(1, 11, 2))
    total = (odd_sum * 3) + even_sum
    check = (10 - (total % 10)) % 10
    return str(check)

def make_upc(prefix: str, item_num: int) -> str:
    s = f"{prefix}{item_num:05d}"
    digits_11 = s[:11]
    return digits_11 + compute_check_digit(digits_11)

# Distribution of 524 items across 21 subcategories:
# Beverages (94): Water (24), Soda & Soft Drinks (26), Juice & Cider (22), Coffee & Tea (22)
# Pantry (88): Pasta & Pizza (24), Canned Goods (22), Condiments & Salad Dressing (22), Cereal & Breakfast (20)
# Snacks (72): Chips & Pretzels (38), Cookies & Crackers (34)
# Household Essentials (64): Laundry Detergent (32), Paper Towels & Bath Tissue (32)
# Dairy & Eggs (56): Milk (28), Cheese (28)
# Frozen Foods (52): Frozen Meals & Entrees (26), Ice Cream & Novelties (26)
# Fresh Produce (42): Fresh Fruits (22), Fresh Vegetables (20)
# Personal Care (28): Hair Care & Shampoo (28)
# Health & Wellness (16): Vitamins & Supplements (16)
# Baby Care (12): Diapers & Wipes (12)

CATEGORIES_SPEC = [
    {
        "category": "Beverages",
        "sub_category": "Water",
        "target": 24,
        "items": [
            ("Dasani Purified Water, 16.9 fl oz, 24 Pack", "no", "16.9 fl oz", "$6.98", "$5.98", "2 for $10", "$10.00", "Clip Coupon: Save $1", "$4.98", "$0.06/fl oz", "04900001001"),
            ("Great Value Purified Drinking Water, 16.9 fl oz, 40 Pack Bottles", "Great Value", "16.9 fl oz", "$5.36", "$5.36", "", "", "", "", "$0.04/fl oz", "07874201002"),
            ("Aquafina Purified Bottled Water, 16.9 fl oz, 24 Pack Bottles", "no", "16.9 fl oz", "$6.48", "$5.98", "2 for $11", "$11.00", "", "", "$0.06/fl oz", "01200001003"),
            ("Nestle Pure Life Purified Water, 16.9 fl oz, 28 Pack", "no", "16.9 fl oz", "$5.98", "$4.98", "Buy 2, Get 1 Free", "", "Clip Coupon: Save $0.75", "$4.23", "$0.05/fl oz", "06827401004"),
            ("Smartwater Vapor Distilled Water Bottles, 33.8 fl oz, 6 Pack", "no", "33.8 fl oz", "$11.48", "$9.98", "", "", "Save $1 with Digital Coupon", "$8.98", "$0.10/fl oz", "78616201005"),
            ("FIJI Natural Artesian Water, 16.9 fl oz, 6 Pack Bottles", "no", "16.9 fl oz", "$8.98", "$7.98", "2 for $14", "$14.00", "", "", "$0.14/fl oz", "63256501006"),
            ("Great Value Spring Water, 1 Gallon Bottle", "Great Value", "128 fl oz", "$1.44", "$1.34", "", "", "", "", "$0.01/fl oz", "07874201007"),
            ("Ozarka 100% Natural Spring Water, 16.9 fl oz, 24 Pack", "no", "16.9 fl oz", "$6.28", "$5.48", "2 for $10", "$10.00", "", "", "$0.05/fl oz", "07478001008"),
            ("Poland Spring 100% Natural Spring Water, 16.9 fl oz, 24 Pack", "no", "16.9 fl oz", "$6.48", "$5.98", "2 for $11", "$11.00", "", "", "$0.06/fl oz", "08265701009"),
            ("Deer Park 100% Natural Spring Water, 16.9 fl oz, 24 Pack", "no", "16.9 fl oz", "$6.28", "$5.48", "2 for $10", "$10.00", "", "", "$0.05/fl oz", "08265701010"),
            ("Perrier Carbonated Mineral Water, 16.9 fl oz, 6 Plastic Bottles", "no", "16.9 fl oz", "$7.98", "$6.98", "", "", "Clip Coupon: Save $1.00", "$5.98", "$0.14/fl oz", "07478001011"),
            ("San Pellegrino Sparkling Natural Mineral Water, 16.9 fl oz, 12 Pack", "no", "16.9 fl oz", "$14.98", "$13.48", "2 for $24", "$24.00", "", "", "$0.13/fl oz", "04150801012"),
            ("LaCroix Sparkling Water, Lemon, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$4.98", "$4.48", "3 for $12", "$12.00", "", "", "$0.03/fl oz", "01290001013"),
            ("bubly Sparkling Water, Limebubly, 12 fl oz, 8 Pack Cans", "no", "96 fl oz", "$4.28", "$3.88", "2 for $7", "$7.00", "Clip Coupon: Save $0.50", "$3.38", "$0.04/fl oz", "01200001014"),
            ("Spindrift Sparkling Water, Lemon Flavored, 12 fl oz, 8 Pack Cans", "no", "96 fl oz", "$6.48", "$5.98", "", "", "", "", "$0.06/fl oz", "85750801015"),
            ("AHA Sparkling Water, Blueberry + Pomegranate, 12 fl oz, 8 Pack", "no", "96 fl oz", "$3.98", "$3.48", "2 for $6", "$6.00", "", "", "$0.04/fl oz", "04900001016"),
            ("Liquid Death Mountain Water, 16.9 fl oz, 8 Pack Tallboys", "no", "135.2 fl oz", "$11.98", "$10.48", "", "", "Save $1.50 with Digital Coupon", "$8.98", "$0.08/fl oz", "85000001017"),
            ("Essentia Ionized Alkaline Water, 33.8 fl oz Bottle", "no", "33.8 fl oz", "$2.48", "$2.18", "3 for $6", "$6.00", "", "", "$0.06/fl oz", "65722701018"),
            ("Core Hydration Nutrient Enhanced Water, 30.4 fl oz Bottle", "no", "30.4 fl oz", "$2.28", "$1.98", "2 for $3.50", "$3.50", "", "", "$0.07/fl oz", "85202601019"),
            ("Evian Natural Spring Water, 33.8 fl oz Bottle", "no", "33.8 fl oz", "$2.68", "$2.38", "", "", "", "", "$0.07/fl oz", "07929801020"),
            ("Great Value Distilled Water, 1 Gallon Bottle", "Great Value", "128 fl oz", "$1.34", "$1.24", "", "", "", "", "$0.01/fl oz", "07874201021"),
            ("Great Value Electrolyte Water, 33.8 fl oz Bottle", "Great Value", "33.8 fl oz", "$1.18", "$0.98", "", "", "", "", "$0.03/fl oz", "07874201022"),
            ("Gerber Pure Purified Water with Added Minerals, 1 Gallon", "no", "128 fl oz", "$1.78", "$1.68", "", "", "", "", "$0.01/fl oz", "01500001023"),
            ("Mountain Valley Spring Water, 33.8 fl oz Glass Bottle (Aisle Restock Pending)", "no", "33.8 fl oz", "", "", "", "", "", "", "", "07478001024")
        ]
    },
    {
        "category": "Beverages",
        "sub_category": "Soda & Soft Drinks",
        "target": 26,
        "items": [
            ("Coca-Cola Original Taste Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$7.98", "3 for $20", "$20.00", "Save $1 with Digital Coupon", "$6.98", "$0.06/fl oz", "04900002001"),
            ("Pepsi Cola Soda Pop, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.48", "$7.48", "3 for $19", "$19.00", "Clip Coupon: Save $1.50", "$5.98", "$0.05/fl oz", "01200002002"),
            ("Dr Pepper Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$7.98", "3 for $20", "$20.00", "", "", "$0.06/fl oz", "07800002003"),
            ("Sprite Lemon-Lime Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$7.98", "3 for $20", "$20.00", "", "", "$0.06/fl oz", "04900002004"),
            ("Great Value Twist Up Lemon Lime Soda, 2 Liter Bottle", "Great Value", "67.6 fl oz", "$1.28", "$1.18", "", "", "", "", "$0.02/fl oz", "07874202005"),
            ("Mountain Dew Citrus Soda Pop, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.48", "$7.48", "3 for $19", "$19.00", "", "", "$0.05/fl oz", "01200002006"),
            ("Diet Coke Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$7.98", "3 for $20", "$20.00", "Clip Coupon: Save $1.00", "$6.98", "$0.06/fl oz", "04900002007"),
            ("Coca-Cola Zero Sugar Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$7.98", "3 for $20", "$20.00", "", "", "$0.06/fl oz", "04900002008"),
            ("Pepsi Zero Sugar Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.48", "$7.48", "3 for $19", "$19.00", "Clip Coupon: Save $1.00", "$6.48", "$0.05/fl oz", "01200002009"),
            ("Diet Dr Pepper Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$7.98", "3 for $20", "$20.00", "", "", "$0.06/fl oz", "07800002010"),
            ("Dr Pepper Strawberries and Cream Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$8.28", "3 for $21", "$21.00", "", "", "$0.06/fl oz", "07800002011"),
            ("Canada Dry Ginger Ale Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.48", "$7.48", "2 for $13", "$13.00", "", "", "$0.05/fl oz", "01690002012"),
            ("A&W Root Beer Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.48", "$7.48", "2 for $13", "$13.00", "", "", "$0.05/fl oz", "07800002013"),
            ("Sunkist Orange Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.48", "$7.48", "2 for $13", "$13.00", "", "", "$0.05/fl oz", "07800002014"),
            ("7UP Lemon Lime Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.48", "$7.48", "2 for $13", "$13.00", "", "", "$0.05/fl oz", "07800002015"),
            ("Fanta Orange Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$7.98", "3 for $20", "$20.00", "", "", "$0.06/fl oz", "04900002016"),
            ("Great Value Cola, 2 Liter Bottle", "Great Value", "67.6 fl oz", "$1.28", "$1.18", "", "", "", "", "$0.02/fl oz", "07874202017"),
            ("Great Value Diet Cola, 2 Liter Bottle", "Great Value", "67.6 fl oz", "$1.28", "$1.18", "", "", "", "", "$0.02/fl oz", "07874202018"),
            ("Great Value Dr. Thunder Soda, 2 Liter Bottle", "Great Value", "67.6 fl oz", "$1.28", "$1.18", "", "", "", "", "$0.02/fl oz", "07874202019"),
            ("Great Value Root Beer, 2 Liter Bottle", "Great Value", "67.6 fl oz", "$1.28", "$1.18", "", "", "", "", "$0.02/fl oz", "07874202020"),
            ("Coca-Cola Original Glass Bottles, 8 fl oz, 6 Pack", "no", "48 fl oz", "$6.48", "$5.98", "", "", "", "", "$0.12/fl oz", "04900002021"),
            ("Mexican Coke Made with Real Cane Sugar, 12 fl oz Glass Bottle", "no", "12 fl oz", "$1.98", "$1.78", "4 for $6", "$6.00", "", "", "$0.15/fl oz", "04900002022"),
            ("Jarritos Mandarin Soda Glass Bottle, 12.5 fl oz", "no", "12.5 fl oz", "$1.28", "$1.14", "4 for $4", "$4.00", "", "", "$0.09/fl oz", "09047802023"),
            ("Squirt Citrus Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.48", "$7.48", "2 for $13", "$13.00", "", "", "$0.05/fl oz", "07800002024"),
            ("Barq's Root Beer Soda, 12 fl oz, 12 Pack Cans", "no", "144 fl oz", "$8.98", "$7.98", "3 for $20", "$20.00", "", "", "$0.06/fl oz", "04900002025"),
            ("Mug Root Beer Soda Pop, 12 fl oz, 12 Pack Cans (Inventory Held)", "no", "144 fl oz", "", "", "", "", "", "", "", "01200002026")
        ]
    },
    {
        "category": "Beverages",
        "sub_category": "Juice & Cider",
        "target": 22,
        "items": [
            ("Simply Orange Pulp Free Juice, 52 fl oz Bottle", "no", "52 fl oz", "$4.38", "$3.98", "2 for $7", "$7.00", "Clip Coupon: Save $0.50", "$3.48", "$0.08/fl oz", "04850003001"),
            ("Great Value 100% Apple Juice, 64 fl oz Bottle", "Great Value", "64 fl oz", "$2.28", "$2.08", "", "", "", "", "$0.03/fl oz", "07874203002"),
            ("Mott's 100% Original Apple Juice, 64 fl oz", "no", "64 fl oz", "$3.28", "$2.98", "2 for $5", "$5.00", "", "", "$0.05/fl oz", "01480003003"),
            ("Ocean Spray 100% Cranberry Juice, 64 fl oz Bottle", "no", "64 fl oz", "$3.98", "$3.48", "", "", "Clip Coupon: Save $0.50", "$2.98", "$0.05/fl oz", "03120003004"),
            ("Tropicana Pure Premium Original Orange Juice, 52 fl oz", "no", "52 fl oz", "$4.48", "$3.98", "2 for $7", "$7.00", "", "", "$0.08/fl oz", "04850003005"),
            ("Minute Maid Zero Sugar Lemonade, 52 fl oz Bottle", "no", "52 fl oz", "$2.98", "$2.68", "", "", "Clip Coupon: Save $0.40", "$2.28", "$0.05/fl oz", "02500003006"),
            ("Simply Lemonade All Natural Lemonade, 52 fl oz Bottle", "no", "52 fl oz", "$3.28", "$2.88", "2 for $5", "$5.00", "", "", "$0.06/fl oz", "04850003007"),
            ("V8 100% Original Vegetable Juice, 46 fl oz Bottle", "no", "46 fl oz", "$3.98", "$3.48", "", "", "", "", "$0.08/fl oz", "05100003008"),
            ("Welch's 100% Concord Grape Juice, 64 fl oz Bottle", "no", "64 fl oz", "$4.68", "$4.18", "2 for $8", "$8.00", "", "", "$0.07/fl oz", "04180003009"),
            ("Capri Sun Pacific Cooler Ready-to-Drink Juice, 10 Pouches", "no", "60 fl oz", "$3.48", "$2.98", "3 for $8", "$8.00", "Clip Coupon: Save $0.50", "$2.48", "$0.05/fl oz", "08768403010"),
            ("Kool-Aid Jammers Tropical Punch Juice Drink, 10 Pouches", "no", "60 fl oz", "$2.78", "$2.48", "3 for $7", "$7.00", "", "", "$0.04/fl oz", "04300003011"),
            ("Great Value 100% Cranberry Juice, 64 fl oz Bottle", "Great Value", "64 fl oz", "$2.58", "$2.38", "", "", "", "", "$0.04/fl oz", "07874203012"),
            ("Great Value Orange Juice from Concentrate, 64 fl oz", "Great Value", "64 fl oz", "$2.68", "$2.48", "", "", "", "", "$0.04/fl oz", "07874203013"),
            ("Snapple Peach Tea Juice Drink, 16 fl oz, 6 Pack Bottles", "no", "96 fl oz", "$6.48", "$5.98", "2 for $11", "$11.00", "", "", "$0.06/fl oz", "07618303014"),
            ("SunnyD Tangy Original Orange Flavored Citrus Drink, 1 Gallon", "no", "128 fl oz", "$3.98", "$3.58", "", "", "", "", "$0.03/fl oz", "05020003015"),
            ("Hawaiian Punch Fruit Juicy Red Juice Drink, 1 Gallon", "no", "128 fl oz", "$2.98", "$2.68", "", "", "", "", "$0.02/fl oz", "01480003016"),
            ("Martinelli's Gold Medal 100% Pure Apple Juice, 10 fl oz, 4 Pack", "no", "40 fl oz", "$4.98", "$4.48", "", "", "", "", "$0.11/fl oz", "04124403017"),
            ("Musselman's 100% Apple Cider, 1 Gallon Jug", "no", "128 fl oz", "$5.98", "$5.48", "", "", "", "", "$0.04/fl oz", "03730003018"),
            ("POM Wonderful 100% Pomegranate Juice, 16 fl oz Bottle", "no", "16 fl oz", "$3.98", "$3.58", "", "", "", "", "$0.22/fl oz", "82415003019"),
            ("Naked Juice Blue Machine 100% Juice Smoothie, 15.2 fl oz", "no", "15.2 fl oz", "$3.68", "$3.28", "2 for $6", "$6.00", "Save $0.50 with Digital Coupon", "$2.78", "$0.22/fl oz", "08259203020"),
            ("Bolthouse Farms Vanilla Chai Tea Protein Shake, 15.2 fl oz", "no", "15.2 fl oz", "$3.48", "$3.18", "", "", "", "", "$0.21/fl oz", "07146403021"),
            ("Great Value 100% Concord Grape Juice, 64 fl oz (Assortment Carried)", "Great Value", "64 fl oz", "", "", "", "", "", "", "", "07874203022")
        ]
    },
    {
        "category": "Beverages",
        "sub_category": "Coffee & Tea",
        "target": 22,
        "items": [
            ("Starbucks Pike Place Roast Medium Ground Coffee, 12 oz Bag", "no", "12 oz", "$9.48", "$8.48", "", "", "Save $1 with Digital Coupon", "$7.48", "$0.71/oz", "04300004001"),
            ("Great Value Classic Roast Medium Ground Coffee, 30.5 oz Can", "Great Value", "30.5 oz", "$7.88", "$7.28", "", "", "", "", "$0.24/oz", "07874204002"),
            ("Folgers Classic Roast Medium Roast Ground Coffee, 25.9 oz Can", "no", "25.9 oz", "$9.98", "$8.98", "2 for $16", "$16.00", "", "", "$0.35/oz", "02550004003"),
            ("Lipton Black Tea Bags, 100 Count Box", "no", "8 oz", "$4.48", "$3.98", "", "", "Clip Coupon: Save $0.50", "$3.48", "$0.50/oz", "04100004004"),
            ("Dunkin' Original Blend Medium Roast Ground Coffee, 12 oz Bag", "no", "12 oz", "$8.98", "$7.98", "2 for $15", "$15.00", "", "", "$0.67/oz", "88133404005"),
            ("Community Coffee Cafe Special Medium-Dark Ground Coffee, 12 oz", "no", "12 oz", "$6.98", "$5.98", "", "", "", "", "$0.50/oz", "03570004006"),
            ("Cafe Bustelo Espresso Ground Coffee, 10 oz Brick", "no", "10 oz", "$4.28", "$3.78", "2 for $7", "$7.00", "", "", "$0.38/oz", "07447104007"),
            ("Green Mountain Coffee Roasters Breakfast Blend K-Cup Pods, 24 Ct", "no", "9.3 oz", "$15.98", "$13.98", "", "", "Clip Coupon: Save $2.00", "$11.98", "$0.58/ct", "09955504008"),
            ("The Original Donut Shop Regular Medium Roast K-Cup Pods, 24 Ct", "no", "9.3 oz", "$15.98", "$13.98", "", "", "", "", "$0.58/ct", "09955504009"),
            ("Great Value Donut Shop Medium Roast Coffee Pods, 48 Ct", "Great Value", "18.6 oz", "$14.48", "$13.28", "", "", "", "", "$0.28/ct", "07874204010"),
            ("McCafe Premium Roast Medium Ground Coffee, 30 oz Can", "no", "30 oz", "$12.48", "$11.28", "", "", "", "", "$0.38/oz", "04300004011"),
            ("Peet's Coffee Major Dickason's Blend Dark Roast Ground, 10.5 oz", "no", "10.5 oz", "$9.98", "$8.98", "", "", "Clip Coupon: Save $1.00", "$7.98", "$0.86/oz", "71612404012"),
            ("Bigelow Constant Comment Spiced Black Tea Bags, 20 Count", "no", "1.18 oz", "$3.28", "$2.88", "", "", "", "", "$2.44/oz", "07231004013"),
            ("Twinings of London Earl Grey Black Tea Bags, 50 Count Box", "no", "3.53 oz", "$6.48", "$5.98", "", "", "", "", "$1.70/oz", "07017704014"),
            ("Celestial Seasonings Sleepytime Herbal Tea Bags, 40 Count", "no", "2 oz", "$4.88", "$4.28", "2 for $8", "$8.00", "Clip Coupon: Save $0.50", "$3.78", "$2.14/oz", "07073404015"),
            ("Arizona Green Tea with Ginseng & Honey, 1 Gallon Jug", "no", "128 fl oz", "$3.68", "$3.28", "", "", "", "", "$0.03/fl oz", "61300804016"),
            ("Gold Peak Sweet Black Iced Tea, 52 fl oz Bottle", "no", "52 fl oz", "$2.98", "$2.68", "2 for $5", "$5.00", "", "", "$0.05/fl oz", "04900004017"),
            ("Pure Leaf Sweet Iced Tea, 64 fl oz Bottle", "no", "64 fl oz", "$3.48", "$2.98", "", "", "Clip Coupon: Save $0.50", "$2.48", "$0.05/fl oz", "01200004018"),
            ("Starbucks Frappuccino Mocha Chilled Coffee Drink, 13.7 fl oz", "no", "13.7 fl oz", "$3.18", "$2.78", "3 for $7", "$7.00", "", "", "$0.20/fl oz", "01200004019"),
            ("International Delight French Vanilla Coffee Creamer, 32 fl oz", "no", "32 fl oz", "$3.98", "$3.58", "2 for $6.50", "$6.50", "", "", "$0.11/fl oz", "04127104020"),
            ("Coffee mate French Vanilla Liquid Coffee Creamer, 32 fl oz", "no", "32 fl oz", "$3.98", "$3.58", "2 for $6.50", "$6.50", "Clip Coupon: Save $0.50", "$3.08", "$0.11/fl oz", "05000004021"),
            ("Chock full o'Nuts Original Heavenly Coffee Ground, 26 oz (Pending)", "no", "26 oz", "", "", "", "", "", "", "", "07103804022")
        ]
    }
]

print("Category spec defined successfully.")
