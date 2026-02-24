from time import sleep, time, localtime
from ili9341 import Display, color565
from machine import Pin, SPI, UART  # type: ignore
from xglcd_font import XglcdFont
from urequests import get, request, Response # type: ignore
import network # type: ignore
import math
import ntptime # type: ignore
import ujson # type: ignore

# Get the distance between two points in Nautical Miles
def get_distance(coords_from, coords_to):
    return 2 * 3443.92 * math.asin(
        math.sqrt(
            (math.sin((coords_to[0] - coords_from[0])*math.pi/360)**2
            + (math.cos(coords_to[0]*math.pi/180) * math.cos(coords_from[0]*math.pi/180) * (math.sin((coords_to[1] - coords_from[1])*math.pi/360)**2))
            )
        )
    )
    
# Get the bearing/track between two points
def get_bearing(coords_from, coords_to):
    lat1 = math.radians(coords_from[0])
    long1 = math.radians(coords_from[1])
    lat2 = math.radians(coords_to[0])
    long2 = math.radians(coords_to[1])
    return math.degrees(math.atan2(
      math.sin(long2 - long1) * math.cos(lat2),
      math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(long2 - long1)
    )) % 360

# Check if a waypoint is ahead of the aircraft, based on the current heading
def is_waypoint_ahead(waypoint):
  heading = vatsim_data["heading"]
  bearing = get_bearing([latitude, longitude], [float(waypoint["pos_lat"]), float(waypoint["pos_long"])])
  return (heading - bearing) % 360 <= 90 or (heading - bearing) % 360 >= 270

# Interface with the display over SPI
spi = SPI(1, baudrate=50000000, sck=Pin(15), mosi=Pin(7))
display = Display(spi, dc=Pin(5), cs=Pin(4), rst=Pin(6), width=320, height=240, rotation=90)

# Retrieve the WLAN interface
wlan_sta = network.WLAN(network.WLAN.IF_STA)

WIDTH = 320
HEIGHT = 240

LARGE_FONT_HEIGHT, LARGE_FONT_WIDTH = 24, 12
SMALL_FONT_HEIGHT, SMALL_FONT_WIDTH = 11, 9

TEXT_COLOUR = color565(255, 255, 255)
TEXT_COLOUR_ACCENT = color565(206, 207, 206)

BACKGROUND_COLOUR = color565(0, 0, 0)
BACKGROUND_COLOUR_ACCENT = color565(106, 105, 100)

SIMBRIEF_ID = open("simbrief_id.txt").readline().strip()
VATSIM_CID = open("vatsim_cid.txt").readline().strip()
SERVER_ADDR = open("server.txt").readline().strip()

LARGE_FONT = XglcdFont('Unispace12x24.c', LARGE_FONT_WIDTH, LARGE_FONT_HEIGHT)
SMALL_FONT = XglcdFont('ArcadePix9x11.c', SMALL_FONT_WIDTH, SMALL_FONT_HEIGHT)

VATSIM_REFRESH_TIME, VATSIM_REFRESH_INTERVAL = 0, 10
SIMBRIEF_REFRESH_TIME, SIMBRIEF_REFRESH_INTERVAL = 0, 60
WEATHER_REFRESH_TIME, WEATHER_REFRESH_INTERVAL = 0, 120
POSITION_REFRESH_TIME, POSITION_REFRESH_INTERVAL = 0, 3

simbrief_updated, vatsim_updated, weather_updated, position_updated = False, False, False, False

ETE_REFRESH_TIME, ETE_REFRESH_INTERVAL, ETE_DISPLAY_TYPE, ETE_DISPLAY_TYPES = 0, 1, 0, 4

simbrief_flightplan = {}
vatsim_data = {}
weather_data = {
  "origin":{},
  "destination":{}
}
position_data = {}
waypoints = []

latitude = -190
longitude = -190
distance_to_destination = 0
distance_to_origin = 0
distance_to_destination_formatted = ""
distance_to_origin_formatted = ""
time_to_destination = 0
progress = 0

def download_simbrief_data():
  global simbrief_flightplan, simbrief_updated
  global SIMBRIEF_REFRESH_TIME

  # Show "Simbrief" in Blue while trying to download data
  draw_large_text_right_aligned("Simbrief", WIDTH - 12, int(HEIGHT - 16 - (LARGE_FONT_HEIGHT / 2)), colour=color565(0, 0, 255), background=BACKGROUND_COLOUR_ACCENT)
  
  try:
    simbrief_flightplan = ujson.loads(get(url="http://{0}/simbrief".format(SERVER_ADDR)).text)["simbrief"]
    draw_large_text_right_aligned("Simbrief", WIDTH - 12, int(HEIGHT - 16 - (LARGE_FONT_HEIGHT / 2)), colour=color565(0, 255, 0), background=BACKGROUND_COLOUR_ACCENT)
    simbrief_updated = True
    SIMBRIEF_REFRESH_TIME = time()
  except:
    draw_large_text_right_aligned("Simbrief", WIDTH - 12, int(HEIGHT - 16 - (LARGE_FONT_HEIGHT / 2)), colour=color565(255, 0, 0), background=BACKGROUND_COLOUR_ACCENT)
    
    # Try again in 15 seconds
    SIMBRIEF_REFRESH_TIME = time() - (SIMBRIEF_REFRESH_INTERVAL - 15)

def download_vatsim_data():
  global vatsim_data, vatsim_updated
  global VATSIM_REFRESH_TIME

  # Show "VATSIM" in Blue while trying to download data
  draw_large_text_at("VATSIM", 12, int(HEIGHT - 16 - (LARGE_FONT_HEIGHT / 2)), colour=color565(0, 0, 255), background=BACKGROUND_COLOUR_ACCENT)
  try:
    # vatsim_data = get(url="https://vatsim-radar.com/api/data/vatsim/pilot/{0}".format(VATSIM_CID)).json()
    vatsim_data = ujson.loads(get(url="http://{0}/vatsim".format(SERVER_ADDR)).text)["vatsim"][0]
    vatsim_updated = True

    # Show "VATSIM" in Green if we were able to retrieve data
    draw_large_text_at("VATSIM", 12, int(HEIGHT - 16 - (LARGE_FONT_HEIGHT / 2)), colour=color565(0, 255, 0), background=BACKGROUND_COLOUR_ACCENT)
    VATSIM_REFRESH_TIME = time()
  except:
    # Otherwise, show it in red
    draw_large_text_at("VATSIM", 12, int(HEIGHT - 16 - (LARGE_FONT_HEIGHT / 2)), colour=color565(255, 0, 0), background=BACKGROUND_COLOUR_ACCENT)

    # Try again in 5 seconds
    VATSIM_REFRESH_TIME = time() - (VATSIM_REFRESH_INTERVAL - 5)
  
# Retrieve weather data
def download_weather_data():
  global vatsim_data, simbrief_flightplan, weather_data, weather_updated
  global WEATHER_REFRESH_TIME

  # Use separate try blocks for origin and destination weather, as the API is temperamental at best
  try:
    weather_data["origin"] = get(url="http://www.aviationweather.gov/api/data/metar?ids={0}&format=json".format(simbrief_flightplan["origin"]["icao_code"])).json()[0]
    weather_updated = True
    WEATHER_REFRESH_TIME = time()
    weather_updated = True
  except Exception as e:
    print("Origin Weather Error:")
    print(e)
  
  try:
    weather_data["destination"] = get(url="http://www.aviationweather.gov/api/data/metar?ids={0}&format=json".format(simbrief_flightplan["destination"]["icao_code"])).json()[0]
    weather_updated = True
    WEATHER_REFRESH_TIME = time()
    weather_updated = True
  except Exception as e:
    print("Destination Weather Error:")
    print(e)
  
  # Try again in 60 seconds
  if time() - WEATHER_REFRESH_TIME > WEATHER_REFRESH_INTERVAL:
    WEATHER_REFRESH_TIME = time() - (WEATHER_REFRESH_INTERVAL - 60)
  
# Retrieve position data from VATSIM
def download_position_data():
    global position_data, position_updated
    global POSITION_REFRESH_TIME
    temp_data = get(url="http://slurper.vatsim.net/users/info?cid={0}".format(VATSIM_CID)).text.split(',')
    if len(temp_data) > 1:
      position_data = {"latitude":float(temp_data[5]),"longitude":float(temp_data[6])}
      position_updated = True
    POSITION_REFRESH_TIME = time()

# Text utilities
def draw_large_text_at(text, x=0, y=0, colour=TEXT_COLOUR, background=BACKGROUND_COLOUR):
  display.draw_text(x, y, text, LARGE_FONT, colour, background=background)

def draw_large_text_centered(text, x=int(WIDTH/2), y=int(HEIGHT/2), colour=TEXT_COLOUR, background=BACKGROUND_COLOUR):
  draw_large_text_at(text, x - int(LARGE_FONT.measure_text(text, spacing=0)/2), y - int(LARGE_FONT_HEIGHT / 2), colour=colour, background=background)
  
def draw_large_text_right_aligned(text, x=int(WIDTH), y=0, colour=TEXT_COLOUR, background=BACKGROUND_COLOUR):
  draw_large_text_at(text, x - LARGE_FONT.measure_text(text, spacing=0), y, colour=colour, background=background)

def draw_small_text_at(text, x=0, y=0, colour=TEXT_COLOUR, background=BACKGROUND_COLOUR):
  display.draw_text(x, y, text, SMALL_FONT, colour, background=background)

def draw_small_text_right_aligned(text, x=int(WIDTH), y=0, colour=TEXT_COLOUR, background=BACKGROUND_COLOUR):
  draw_small_text_at(text, x - SMALL_FONT.measure_text(text, spacing=0), y, colour=colour, background=background)

def draw_small_text_centered(text, x=int(WIDTH/2), y=int(HEIGHT/2), colour=TEXT_COLOUR, background=BACKGROUND_COLOUR):
  draw_small_text_at(text, x - int(SMALL_FONT.measure_text(text, spacing=0) / 2), y - int(SMALL_FONT_HEIGHT / 2), colour=colour, background=background)

def draw_wifi_status():
  if wlan_sta.isconnected():
    draw_large_text_centered("Wi-Fi", y=int(HEIGHT - 16), colour=color565(0, 255, 0), background=BACKGROUND_COLOUR_ACCENT)
  else:
    draw_large_text_centered("Wi-Fi", y=int(HEIGHT - 16), colour=color565(255, 0, 0), background=BACKGROUND_COLOUR_ACCENT)

def connect_wifi():
    if not wlan_sta.isconnected():
      try:
        wlan_sta.active(True)
      except:
        pass
      
      # Connect to WLAN with the credentials stored on the board
      with open('wifi_ssid.txt', 'r') as f:
        wifi_ssid = f.readline()
        display.draw_text8x8(0, 0, "Connecting to: " + wifi_ssid, color565(255, 0, 255))
      with open('wifi_password.txt', 'r') as f:
        wifi_password = f.readline()
        wlan_sta.connect(wifi_ssid, wifi_password)
        while not wlan_sta.isconnected():
          sleep(0.5)
      
      display.clear(color565(64, 0, 255))
      display.draw_text8x8(0, 0, "Connected to: " + wifi_ssid, color565(255, 0, 255))
      display.draw_text8x8(0, 8, "IP Address: " + wlan_sta.ipconfig('addr4')[0], color565(255, 0, 255))
      ntptime.settime()

      # Allow time to enter file transfer mode; in the main program loop, the CPU never yields
      sleep(5)

def prepare_interface():
  display.clear(color565(0, 0, 0))

  # Draw top and bottom bars
  display.fill_rectangle(0, 0, WIDTH, 32, BACKGROUND_COLOUR)
  display.fill_rectangle(0, HEIGHT - 32, WIDTH, 32, BACKGROUND_COLOUR_ACCENT)

  # Logo and flavour text
  display.draw_image('tail44x30.raw', 1, 1, 44, 30)
  draw_large_text_centered('Air Anteater', y=16, colour=TEXT_COLOUR_ACCENT, background=BACKGROUND_COLOUR)

  # Lower bar status information
  # Draw the "VATSIM", "Wi-Fi" and "Simbrief" indicators
  draw_large_text_at("VATSIM", 12, int(HEIGHT - 16 - (LARGE_FONT_HEIGHT / 2)), colour=color565(255, 255, 255), background=BACKGROUND_COLOUR_ACCENT)
  draw_large_text_right_aligned("Simbrief", WIDTH - 12, int(HEIGHT - 16 - (LARGE_FONT_HEIGHT / 2)), colour=color565(255, 255, 255), background=BACKGROUND_COLOUR_ACCENT)
  draw_wifi_status()
    
def download_loop():
  global setup_complete
  global vatsim_data, VATSIM_REFRESH_TIME, VATSIM_REFRESH_INTERVAL
  global simbrief_flightplan, SIMBRIEF_REFRESH_TIME, SIMBRIEF_REFRESH_INTERVAL
  global weather_data, WEATHER_REFRESH_TIME, WEATHER_REFRESH_INTERVAL
  
  # Refresh data from each source only when needed
  if setup_complete:
    if time() - SIMBRIEF_REFRESH_TIME > SIMBRIEF_REFRESH_INTERVAL:
      download_simbrief_data()
    
    if time() - VATSIM_REFRESH_TIME > VATSIM_REFRESH_INTERVAL:
      download_vatsim_data()
    
    if time() - WEATHER_REFRESH_TIME > WEATHER_REFRESH_INTERVAL:
      download_weather_data()
      
    if time() - POSITION_REFRESH_TIME > POSITION_REFRESH_INTERVAL:
      download_position_data()

def loop():
  global vatsim_data, simbrief_flightplan, weather_data, position_data
  global vatsim_updated, simbrief_updated, weather_updated, position_updated
  global ETE_DISPLAY_TYPE, ETE_DISPLAY_TYPES, ETE_REFRESH_INTERVAL, ETE_REFRESH_TIME
  global latitude, longitude, distance_to_destination, distance_to_origin, distance_to_origin_formatted, distance_to_destination_formatted, time_to_destination, waypoints
  global WIDTH, HEIGHT
  
  # Update WLAN status. Show "Wi-Fi" in green when connected, and red when disconnected.
  draw_wifi_status()

  # Update the position of the aircraft
  if position_data and position_updated:
    latitude = float(position_data["latitude"])
    longitude = float(position_data["longitude"])
    if simbrief_flightplan:
      display.fill_rectangle(0, 64, WIDTH, 24, BACKGROUND_COLOUR)
      display.fill_rectangle(0, 112, WIDTH, 64, BACKGROUND_COLOUR)
  
  if position_data and vatsim_data and simbrief_flightplan and (vatsim_updated or simbrief_updated or position_updated):
    # Calculate distances from origin and to destination
    distance_to_origin = get_distance([latitude, longitude], [float(simbrief_flightplan["origin"]["pos_lat"]), float(simbrief_flightplan["origin"]["pos_long"])])
    distance_to_destination = get_distance([latitude, longitude], [float(simbrief_flightplan["destination"]["pos_lat"]), float(simbrief_flightplan["destination"]["pos_long"])])
    distance_to_origin_formatted = "{0}nm".format(round(distance_to_origin, 1) if distance_to_origin < 9.95 else int(distance_to_origin))

    # The distance to destination should be right-aligned for consistency
    distance_to_destination_formatted = "{:>4}nm".format(round(distance_to_destination, 1) if distance_to_destination < 9.95 else int(distance_to_destination))
    progress = (distance_to_origin) / (distance_to_origin + distance_to_destination)
    
    # Draw progress bar and plane image

    # The image should be displayed at x = 0 through 28 at the start of the flight, to x = 291 through 319 at the end of the flight
    image_x_pos = int(progress * (WIDTH - 29))
    if vatsim_data["groundspeed"] <= 30:
      image = 'Plane Ground29x24.raw'
    elif abs(vatsim_data["altitude"] - int(vatsim_data["flight_plan"]["altitude"])) < 500:
      image = 'Plane Cruise29x24.raw'
    elif distance_to_destination < distance_to_origin:
      image = 'Plane Descending29x24.raw'
    else:
      image = 'Plane Climbing29x24.raw'
    display.draw_image(image, image_x_pos, 64, 29, 24)
    if image_x_pos > 4:
      display.draw_rectangle(0, 75, image_x_pos - 4, 2, TEXT_COLOUR)
  
  if vatsim_data and vatsim_updated:
    # Calculate time to destination
    if vatsim_data["groundspeed"] <= 30:
      time_to_destination = 0
    else:
      time_to_destination = distance_to_destination / vatsim_data["groundspeed"]
  
  # Update the flight number, origin and destination
  if simbrief_flightplan and simbrief_updated:
    display.fill_rectangle(44, 0, WIDTH - 44, 32, BACKGROUND_COLOUR)
    draw_large_text_centered("{0}{1}".format(simbrief_flightplan["general"]["icao_airline"], simbrief_flightplan["general"]["flight_number"]), y=16, colour=TEXT_COLOUR_ACCENT, background=BACKGROUND_COLOUR)
    draw_large_text_at(simbrief_flightplan["origin"]["icao_code"], x=12, y=40)
    draw_large_text_right_aligned(simbrief_flightplan["destination"]["icao_code"], x=WIDTH - 12, y=40)
  
  # Display weather data and nearest waypoints
  if vatsim_data and simbrief_flightplan and position_data and (position_updated or simbrief_updated or weather_updated):
    y_position = 112
    try:
      if distance_to_origin < distance_to_destination:
        display_weather_data = weather_data["origin"]
      else:
        display_weather_data = weather_data["destination"]
      
      # Format strings depending on whether closer to origin or destination and calculate the maximum width of text
      strings = [
        "{0}C".format(display_weather_data["temp"]),
        "{:04d}hPa".format(display_weather_data["altim"]),
        "{:03d}@{:02d}kt".format(display_weather_data["wdir"], display_weather_data["wspd"])
      ]
    except:
      strings = [
        "No weather",
        "data found"
      ]

    # Calculate the amount of horizontal space taken up by the weather display, in order to set appropriate widths for the columns next to it
    weather_width = max([SMALL_FONT.measure_text(text) for text in strings])
    
    # Display the weather.
    # If the aircraft is closer to the origin than destination, display the weather AT the origin on the LEFT side
    # If the aircraft is closer to the destination than origin, display the weather AT the destination on the RIGHT side
    if distance_to_origin > distance_to_destination:
      sidebar_x_pos = SMALL_FONT_WIDTH
      weather_pos = WIDTH - SMALL_FONT_WIDTH
      #display.draw_rectangle(weather_pos - weather_width - 1 - SMALL_FONT_WIDTH, 112, 2, 5*SMALL_FONT_HEIGHT, TEXT_COLOUR)
      for text in strings:
        draw_small_text_right_aligned(text, x=weather_pos - 1, y=y_position)
        y_position += SMALL_FONT_HEIGHT
    else:
      sidebar_x_pos = (2 * SMALL_FONT_WIDTH) + weather_width
      weather_pos = SMALL_FONT_WIDTH
      #display.draw_rectangle(sidebar_x_pos - 1, 112, 2, 5*SMALL_FONT_HEIGHT, TEXT_COLOUR)
      for text in strings:
        draw_small_text_at(text, x=weather_pos - 1, y=y_position)
        y_position += SMALL_FONT_HEIGHT
    
    # If there are no waypoints in the flightplan ahead of the aircraft, use the destination instead
    try:
      closest_waypoints = sorted(simbrief_flightplan["navlog"]["fix"], key=lambda waypoint: get_distance([latitude, longitude], [float(waypoint["pos_lat"]), float(waypoint["pos_long"])]))
      closest_waypoint = next(filter(is_waypoint_ahead, closest_waypoints))
      waypoints = (simbrief_flightplan["navlog"]["fix"]) if vatsim_data["groundspeed"] >= 30 else []
    except:
      closest_waypoint = simbrief_flightplan["destination"]
      closest_waypoint["ident"] = closest_waypoint["icao_code"]
      waypoints = [closest_waypoint]
    
    y_position = 112

    # If the aircraft is close to the origin AND below normal climb speeds, we assume the aircraft is not yet climbing, so display takeoff data from Simbrief
    if vatsim_data["groundspeed"] <= 200 and distance_to_origin < 5 and distance_to_origin < distance_to_destination:
      print("Takeoff Data")
      # Show takeoff data
      # RW FLP FLX V1 VR V2
      columns = ["RW","FLP","FLX","V1","VR","V2"]
      
      # Filter to only show data for the planned runway
      selected_runway = next(filter(lambda x: x["identifier"] == simbrief_flightplan["tlr"]["takeoff"]["conditions"]["planned_runway"], simbrief_flightplan["tlr"]["takeoff"]["runway"]))
      values = [
        selected_runway["identifier"],
        selected_runway["flap_setting"],
        selected_runway["flex_temperature"],
        selected_runway["speeds_v1"],
        selected_runway["speeds_vr"],
        selected_runway["speeds_v2"],
      ]

      # Set up 6 columns (Runway, Flaps, Flex Temp, V1, VR, V2)
      column_width = (WIDTH - (3 * SMALL_FONT_WIDTH) - weather_width) / len(columns)
      x_position = sidebar_x_pos
      for column in columns:
        draw_small_text_centered(column, x=math.floor(x_position + column_width / 2), y = y_position + math.ceil(SMALL_FONT_HEIGHT / 2))
        x_position += column_width
      y_position += SMALL_FONT_HEIGHT
      x_position = sidebar_x_pos

      for value in values:
        draw_small_text_centered(value, x=math.floor(x_position + column_width / 2), y = y_position + math.ceil(SMALL_FONT_HEIGHT / 2))
        x_position += column_width
    
    # If the aircraft is close to the destination airport, we assume the aircraft is preparing for landing, so display landing data from Simbrief
    elif distance_to_destination < distance_to_origin and distance_to_destination < 10:
      print("Landing Data")
      # Show landing data
      columns = ["RW","ILS","CRS","ELV","LDA"]
      # Filter runways to only:
      # - The filed runway, and/or;
      # - Runways with a headwind.
      runways = filter(lambda x: int(x["headwind_component"]) > 0 or x["identifier"] == simbrief_flightplan["tlr"]["landing"]["conditions"]["planned_runway"], simbrief_flightplan["tlr"]["landing"]["runway"])
      values = [
        [
          runway["identifier"],
          runway["ils_frequency"],
          "{:03d}".format(int(runway["magnetic_course"])),
          runway["elevation"],
          runway["length_lda"]
        ] for runway in runways
      ]
      
      # Set up columns (Runway, ILS frequency, heading, elevation, landing length)
      column_width = (WIDTH - (3 * SMALL_FONT_WIDTH) - weather_width - 1) / len(columns)
      x_position = sidebar_x_pos
      for column in columns:
        draw_small_text_centered(column, x=math.floor(x_position + column_width / 2), y = y_position + math.ceil(SMALL_FONT_HEIGHT / 2))
        x_position += column_width
      y_position += SMALL_FONT_HEIGHT

      for value_set in values:
        x_position = sidebar_x_pos
        for value in value_set:
          draw_small_text_centered(value, x=math.floor(x_position + column_width / 2), y = y_position + math.ceil(SMALL_FONT_HEIGHT / 2))
          x_position += column_width
        y_position += SMALL_FONT_HEIGHT
      
      # Show the VREF
      draw_small_text_centered(
        "VREF {0}kt".format(simbrief_flightplan["tlr"]["landing"]["distance_" + simbrief_flightplan["tlr"]["landing"]["conditions"]["surface_condition"]]["speeds_vref"]),
        x = int(sidebar_x_pos + (WIDTH - (3 * LARGE_FONT_WIDTH) - weather_width)/2),
        y = y_position + math.ceil(SMALL_FONT_HEIGHT / 2)
      )
    
    else:
      # Show navlog
      closest_waypoint_index = next((i for i, item in enumerate(waypoints) if item["ident"] == closest_waypoint["ident"]), 0)
      filtered_waypoints = waypoints[closest_waypoint_index:]
      column_width = math.floor((WIDTH - (3 * LARGE_FONT_WIDTH) - weather_width) / 3)

      # Show at most 5 waypoints
      for i in range(0, min(5, len(filtered_waypoints))):
        prev_latitude = latitude if i == 0 else float(filtered_waypoints[i - 1]["pos_lat"])
        prev_longitude = longitude if i == 0 else float(filtered_waypoints[i - 1]["pos_long"])
        x_position = sidebar_x_pos

        # Get the distance of this leg (i.e. from the previous waypoint to this waypoint)  
        distance = get_distance([prev_latitude, prev_longitude], [float(filtered_waypoints[i]["pos_lat"]), float(filtered_waypoints[i]["pos_long"])])

        # Display for each waypoint the identifier, leg distance and leg track
        for text in [
            filtered_waypoints[i]["ident"],
            "{0}nm".format(round(distance, 1) if distance < 9.95 else int(distance)),
            "{:03d}".format(int(get_bearing([prev_latitude, prev_longitude], [float(filtered_waypoints[i]["pos_lat"]), float(filtered_waypoints[i]["pos_long"])])))
            ]:
          draw_small_text_centered(text, x=x_position + int(column_width / 2), y = y_position + math.ceil(SMALL_FONT_HEIGHT / 2))
          x_position += column_width
        y_position += SMALL_FONT_HEIGHT
      
  # Display Distance/Time to Destination or arrival time
  if time() - ETE_REFRESH_TIME > ETE_REFRESH_INTERVAL:
    ETE_REFRESH_TIME = time()
    display.fill_rectangle(0, 88, WIDTH, 24, BACKGROUND_COLOUR)
    
    ETE_DISPLAY_TYPE = (ETE_DISPLAY_TYPE + 1) % ETE_DISPLAY_TYPES

    time_tuple = localtime(time() + (int(simbrief_flightplan["destination"]["timezone"]) * 3600 if ETE_DISPLAY_TYPE == 0 else 0) + int(time_to_destination * 3600))
    if ETE_DISPLAY_TYPE == 0 and vatsim_data and time_to_destination:
      # Local time
      ete_display_text = "{:02d}{:02d}L".format(time_tuple[3], time_tuple[4])
    elif ETE_DISPLAY_TYPE == 1 and vatsim_data and time_to_destination:
      # UTC / Z time
      ete_display_text = "{:02d}{:02d}Z".format(time_tuple[3], time_tuple[4])
    elif ETE_DISPLAY_TYPE == 2 and vatsim_data and time_to_destination:
      # ETE Remaining
      ete_display_text = "{:02d}".format(math.floor(time_to_destination)) + ":{:02d}".format(int(60*(time_to_destination % 1)))
    elif position_data:
      # Distance
      ete_display_text = "{0}".format(distance_to_destination_formatted)
    else:
      ete_display_text = ""
    
    draw_large_text_at(distance_to_origin_formatted, x=12, y=88)
    draw_large_text_right_aligned(ete_display_text, x=WIDTH - 12, y=88)
  
  # If either VATSIM or Simbrief data has changed
  if vatsim_data and simbrief_flightplan and (vatsim_updated or simbrief_updated):
    display.fill_rectangle(0, 184, WIDTH, 24, BACKGROUND_COLOUR)
    # Update the bottom row (Altitude, Ground Speed, XPDR)
    # Display the altitude of the aircraft as either altitude or flight level depending on the transition altitude
    if (distance_to_destination < distance_to_origin and vatsim_data["altitude"] > int(simbrief_flightplan["destination"]["trans_level"])) or (distance_to_origin < distance_to_destination and vatsim_data["altitude"] > int(simbrief_flightplan["origin"]["trans_alt"])):
      draw_large_text_at("FL{:03d}".format(math.floor(vatsim_data["altitude"] / 100)), x=12, y=184)
    else:
      draw_large_text_at("{:>5}ft".format(vatsim_data["altitude"]), x=12, y=184)
    draw_large_text_centered("GS {:>3}".format(vatsim_data["groundspeed"]), x=int(WIDTH / 2), y=int(184 + LARGE_FONT_HEIGHT / 2))
    draw_large_text_right_aligned("XPDR {:>4}".format(vatsim_data["transponder"]), x=WIDTH - 12, y=184)
  
  simbrief_updated = False
  vatsim_updated = False
  weather_updated = False
  position_updated = False
  sleep(0.5)
  return

def main():
  global vatsim_updated, simbrief_updated, setup_complete
  
  display.clear(color565(64, 0, 255))
  sleep(1)

  connect_wifi()
  prepare_interface()
  config = ujson.dumps({'simbrief_id':SIMBRIEF_ID, 'vatsim_cid':VATSIM_CID})
  request = get(url="http://{0}/".format(SERVER_ADDR), data=config)

  setup_complete = True
  download_vatsim_data()
  download_simbrief_data()
  download_weather_data()
  download_position_data()
  
  while True:
    connect_wifi()
    download_loop()
    loop()

main()

















