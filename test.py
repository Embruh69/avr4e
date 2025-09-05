import math
def get_in_game_date(irl_day_number):
    months = [
        "🌸Terra", "🌸Marzen", "🌞Saturna", "🌞Venira",
        "🍂Juvion", "🍂Mercion", "🧊Urantis", "🧊Nevaris"
    ]

    total_irl_days_in_year = 28
    irl_day_in_year = (irl_day_number - 1) % total_irl_days_in_year + 1

    month_index = (int(math.floor((irl_day_in_year - 1) * 2 / 7))) % len(months)
    print(month_index)
    match (irl_day_in_year-1) % 7:
        case 0:
            return f"1 {months[month_index]} - 8 {months[month_index]}"
        case 1: 
            return f"9 {months[month_index]} - 16 {months[month_index]}"
        case 2: 
            return f"17 {months[month_index]} - 24 {months[month_index]}"
        case 3: 
            return f"25 {months[month_index]} - 4 {months[month_index+1]}"
        case 4: 
            return f"5 {months[month_index]} - 12 {months[month_index]}"
        case 5: 
            return f"13 {months[month_index]} - 20 {months[month_index]}"
        case 6: 
            return f"21 {months[month_index]} - 28 {months[month_index]}"
        case 7:
            return f"1 {months[month_index]} - 8 {months[month_index]}"
    raise ValueError("Invalid week number computation.")

print(get_in_game_date(57))