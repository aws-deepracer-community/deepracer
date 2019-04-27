from __future__ import print_function

import time

# only needed for fake driver setup
import boto3
# gym
import gym
import numpy as np
from gym import spaces
from PIL import Image
import os
import math

# Type of worker
SIMULATION_WORKER = "SIMULATION_WORKER"
SAGEMAKER_TRAINING_WORKER = "SAGEMAKER_TRAINING_WORKER"

node_type = os.environ.get("NODE_TYPE", SIMULATION_WORKER)

if node_type == SIMULATION_WORKER:
    import rospy
    from ackermann_msgs.msg import AckermannDriveStamped
    from gazebo_msgs.msg import ModelState
    from gazebo_msgs.srv import SetModelState

    from sensor_msgs.msg import Image as sensor_image
    from deepracer_msgs.msg import Progress

TRAINING_IMAGE_SIZE = (160, 120)
FINISH_LINE = 100

# REWARD ENUM
CRASHED = 0
NO_PROGRESS = -1
FINISHED = 10000000.0
MAX_STEPS = 1000000

# WORLD NAME
EASY_TRACK_WORLD = 'easy_track'
MEDIUM_TRACK_WORLD = 'medium_track'
HARD_TRACK_WORLD = 'hard_track'
HARD_SPEED_TRACK_WORLD = 'hard_speed_track'
HARD_LOOPY_TRACK_WORLD = 'hard_loopy_track'

# SLEEP INTERVALS
SLEEP_AFTER_RESET_TIME_IN_SECOND = 0.5
SLEEP_BETWEEN_ACTION_AND_REWARD_CALCULATION_TIME_IN_SECOND = 0.1
SLEEP_WAITING_FOR_IMAGE_TIME_IN_SECOND = 0.01

### Gym Env ###
class DeepRacerEnv(gym.Env):
    def __init__(self):

        screen_height = TRAINING_IMAGE_SIZE[1]
        screen_width = TRAINING_IMAGE_SIZE[0]

        self.on_track = 0
        self.progress = 0
        self.yaw = 0
        self.x = 0
        self.y = 0
        self.z = 0
        self.distance_from_center = 0
        self.distance_from_border_1 = 0
        self.distance_from_border_2 = 0
        self.steps = 0
        self.episodes = 0
        self.progress_at_beginning_of_race = 0
        self.prev_closest_waypoint_index = 0
        self.closest_waypoint_index = 0

        # actions -> steering angle, throttle
        self.action_space = spaces.Box(low=np.array([-1, 0]), high=np.array([+1, +1]), dtype=np.float32)

        # given image from simulator
        self.observation_space = spaces.Box(low=0, high=255,
                                            shape=(screen_height, screen_width, 3), dtype=np.uint8)

        if node_type == SIMULATION_WORKER:
            # ROS initialization
            self.ack_publisher = rospy.Publisher('/vesc/low_level/ackermann_cmd_mux/output',
                                                 AckermannDriveStamped, queue_size=100)
            self.racecar_service = rospy.ServiceProxy('/gazebo/set_model_state', SetModelState)
            rospy.init_node('rl_coach', anonymous=True)

            # Subscribe to ROS topics and register callbacks
            rospy.Subscriber('/progress', Progress, self.callback_progress)
            rospy.Subscriber('/camera/zed/rgb/image_rect_color', sensor_image, self.callback_image)
            self.world_name = rospy.get_param('WORLD_NAME')
            self.set_waypoints()
            self.track_length = self.calculate_track_length()
            
            self.aws_region = rospy.get_param('ROS_AWS_REGION')

        self.reward_in_episode = 0
        self.prev_progress = 0

    def reset(self):
        if node_type == SAGEMAKER_TRAINING_WORKER:
            return self.observation_space.sample()
        print('Total Reward Reward=%.2f' % self.reward_in_episode,
              'Total Steps=%.2f' % self.steps)
        self.send_reward_to_cloudwatch(self.reward_in_episode)

        self.reward_in_episode = 0
        self.reward = None
        self.done = False
        self.next_state = None
        self.image = None
        self.steps = 0
        self.episodes += 1
        self.prev_progress = 0
        self.total_progress = 0
        self.action_taken = 2 #straight
        self.prev_action = 2 #straight
        self.prev_closest_waypoint_index = 0 #always starts from first waypoint
        self.closest_waypoint_index = 0

        # Reset car in Gazebo
        self.send_action(0, 0)  # set the throttle to 0
        self.racecar_reset()
        self.steering_angle = 0.0
        self.throttle = 0.0
        self.action_taken = 2.0

        self.infer_reward_state(0, 0)
        return self.next_state

    def racecar_reset(self):
        rospy.wait_for_service('gazebo/set_model_state')

        modelState = ModelState()
        modelState.pose.position.z = 0
        modelState.pose.orientation.x = 0
        modelState.pose.orientation.y = 0
        modelState.pose.orientation.z = 0
        modelState.pose.orientation.w = 0  # Use this to randomize the orientation of the car
        modelState.twist.linear.x = 0
        modelState.twist.linear.y = 0
        modelState.twist.linear.z = 0
        modelState.twist.angular.x = 0
        modelState.twist.angular.y = 0
        modelState.twist.angular.z = 0
        modelState.model_name = 'racecar'

        if self.world_name.startswith(MEDIUM_TRACK_WORLD):
            modelState.pose.position.x = -1.40
            modelState.pose.position.y = 2.13
        elif self.world_name.startswith(EASY_TRACK_WORLD):
            modelState.pose.position.x = -1.44
            modelState.pose.position.y = -0.06
        elif self.world_name.startswith(HARD_SPEED_TRACK_WORLD):
            modelState.pose.position.x = 1.8
            modelState.pose.position.y = 0.60
        elif self.world_name.startswith(HARD_LOOPY_TRACK_WORLD):
            modelState.pose.position.x = 2.08
            modelState.pose.position.y = 0.3081
        elif self.world_name.startswith(HARD_TRACK_WORLD):
            modelState.pose.position.x = 1.75
            modelState.pose.position.y = 0.6
            
            def toQuaternion(pitch, roll, yaw):
                cy = np.cos(yaw * 0.5)
                sy = np.sin(yaw * 0.5)
                cr = np.cos(roll * 0.5)
                sr = np.sin(roll * 0.5)
                cp = np.cos(pitch * 0.5)
                sp = np.sin(pitch * 0.5)

                w = cy * cr * cp + sy * sr * sp
                x = cy * sr * cp - sy * cr * sp
                y = cy * cr * sp + sy * sr * cp
                z = sy * cr * cp - cy * sr * sp
                return [x, y, z, w]

            #clockwise
            quaternion = toQuaternion(roll=0.0, pitch=0.0, yaw=np.pi)
            #anti-clockwise
            quaternion = toQuaternion(roll=0.0, pitch=0.0, yaw=0.0)
            modelState.pose.orientation.x = quaternion[0]
            modelState.pose.orientation.y = quaternion[1]
            modelState.pose.orientation.z = quaternion[2]
            modelState.pose.orientation.w = quaternion[3]
            
        else:
            raise ValueError("Unknown simulation world: {}".format(self.world_name))

        self.racecar_service(modelState)
        time.sleep(SLEEP_AFTER_RESET_TIME_IN_SECOND)
        self.progress_at_beginning_of_race = self.progress

    def step(self, action):
        if node_type == SAGEMAKER_TRAINING_WORKER:
            return self.observation_space.sample(), 0, False, {}

        # initialize rewards, next_state, done
        self.reward = None
        self.done = False
        self.next_state = None

        steering_angle = float(action[0])
        throttle = float(action[1])
        self.steps += 1
        self.send_action(steering_angle, throttle)
        time.sleep(SLEEP_BETWEEN_ACTION_AND_REWARD_CALCULATION_TIME_IN_SECOND)
        self.infer_reward_state(steering_angle, throttle)

        info = {}  # additional data, not to be used for training
        return self.next_state, self.reward, self.done, info

    def callback_image(self, data):
        self.image = data

    def callback_progress(self, data):
        self.on_track = not (data.off_track)
        self.progress = data.progress
        self.yaw = data.yaw
        self.x = data.x
        self.y = data.y
        self.z = data.z
        self.distance_from_center = data.distance_from_center
        self.distance_from_border_1 = data.distance_from_border_1
        self.distance_from_border_2 = data.distance_from_border_2

    def send_action(self, steering_angle, throttle):
        ack_msg = AckermannDriveStamped()
        ack_msg.header.stamp = rospy.Time.now()
        ack_msg.drive.steering_angle = steering_angle
        ack_msg.drive.speed = throttle
        self.ack_publisher.publish(ack_msg)

    def reward_function(self, on_track, x, y, distance_from_center, car_orientation, progress, steps,
                        throttle, steering, track_width, waypoints, closest_waypoints):
        
        reward = 0
        if self.distance_from_border_1 >= 0.0 and distance_from_center <= 0.013:
            reward += 4.0
       #elif distance_from_center >= 0.02 and distance_from_center <= 0.03:
       #    return 0.3
       #elif distance_from_center >= 0.03 and distance_from_center <= 0.05:
       #    return 0.1

        # stick close to border_1 by staying between 0 and track_width distance
        
#        reward += (np.interp(track_width - self.distance_from_border_1, (0, track_width), (0,1))) * 4
        # reward going further
        reward += np.interp(progress, (0, 100), (0, 1)) *5
        # reward going faster
        reward += np.interp(throttle, (0, 10), (0, 1))*3
        return reward

    def infer_reward_state(self, steering_angle, throttle):
        # Wait till we have a image from the camera
        while not self.image:
            time.sleep(SLEEP_WAITING_FOR_IMAGE_TIME_IN_SECOND)

        # Car environment spits out BGR images by default. Converting to the
        # image to RGB.
        image = Image.frombytes('RGB', (self.image.width, self.image.height),
                                self.image.data, 'raw', 'RGB', 0, 1)
        # resize image ans perform anti-aliasing
        image = image.resize(TRAINING_IMAGE_SIZE, resample=2).convert("RGB")
        state = np.array(image)

       
        #total_progress = self.progress - self.progress_at_beginning_of_race
        #self.prev_progress = total_progress
        
        # calculate the closest way point 
        self.closest_waypoint_index = self.get_closest_waypoint()
        # calculate the current progress with respect to the way points
        current_progress = self.calculate_current_progress(self.closest_waypoint_index, self.prev_closest_waypoint_index)
        self.total_progress = current_progress + self.prev_progress
        # re-assign the prev progress and way point variables
        self.prev_progress = self.total_progress
        self.prev_closest_waypoint_index = self.closest_waypoint_index

        done = False
        on_track = self.on_track
        if on_track != 1:
            reward = CRASHED
            done = True
        #elif total_progress >= FINISH_LINE:  # reached max waypoints
        #    print("Congratulations! You finished the race!")
        #    if self.steps == 0:
        #        reward = 0.0
        #        done = False
        #    else:
        #        reward = FINISHED / self.steps
        #        done = True
        else:
            reward = self.reward_function(on_track, self.x, self.y, self.distance_from_center, self.yaw,
                                          self.total_progress, self.steps, throttle, steering_angle, self.road_width,
                                          list(self.waypoints), self.get_closest_waypoint())
            
            reward += 0.5 #reward bonus for surviving
            
            #smooth
            #if self.action_taken == self.prev_action:
            #    reward += 0.5
            self.prev_action = self.action_taken

        print('Step No=%.2f' % self.steps,
              'Step Reward=%.2f' % reward)

        self.reward_in_episode += reward
        self.reward = reward
        self.done = done
        self.next_state = state
        
        # Trace logs to help us debug and visualize the training runs
        stdout_ = 'SIM_TRACE_LOG:%d,%d,%.4f,%.4f,%.4f,%.2f,%.2f,%d,%.4f,%.4f,%d,%s,%s,%.4f,%d,%d,%.2f,%.4f,%.4f,%.4f,%s\n' % (
        self.episodes, self.steps, self.x, self.y,
        self.yaw,
        self.steering_angle,
        self.throttle,
        self.action_taken,
        self.reward,
        self.total_progress,
        0, #self.get_waypoint_action(), #the expert action at the next waypoint
        self.done,
        self.on_track,
        current_progress,
        0, #self.initidxWayPoint, #starting waypoint for an episode
        self.closest_waypoint_index,
        self.track_length,
        self.distance_from_center,
        self.distance_from_border_1,
        self.distance_from_border_2,
        time.time())
        print(stdout_)

    def send_reward_to_cloudwatch(self, reward):
        if os.environ.get("LOCAL") != None:
            print("Reward " + str(reward))
        else:
            session = boto3.session.Session()
            cloudwatch_client = session.client('cloudwatch', region_name=self.aws_region)
            cloudwatch_client.put_metric_data(
                MetricData=[
                    {
                        'MetricName': 'DeepRacerRewardPerEpisode',
                        'Unit': 'None',
                        'Value': reward
                    },
                ],
                Namespace='AWSRoboMakerSimulation'
            )

    def set_waypoints(self):
        if self.world_name.startswith(MEDIUM_TRACK_WORLD):
            self.waypoints = vertices = np.zeros((8, 2))
            self.road_width = 0.50
            vertices[0][0] = -0.99; vertices[0][1] = 2.25;
            vertices[1][0] = 0.69;  vertices[1][1] = 2.26;
            vertices[2][0] = 1.37;  vertices[2][1] = 1.67;
            vertices[3][0] = 1.48;  vertices[3][1] = -1.54;
            vertices[4][0] = 0.81;  vertices[4][1] = -2.44;
            vertices[5][0] = -1.25; vertices[5][1] = -2.30;
            vertices[6][0] = -1.67; vertices[6][1] = -1.64;
            vertices[7][0] = -1.73; vertices[7][1] = 1.63;
        elif self.world_name.startswith(EASY_TRACK_WORLD):
            self.waypoints = vertices = np.zeros((2, 2))
            self.road_width = 0.90
            vertices[0][0] = -1.08;   vertices[0][1] = -0.05;
            vertices[1][0] =  1.08;   vertices[1][1] = -0.05;
        elif self.world_name.startswith(HARD_LOOPY_TRACK_WORLD):
            self.waypoints = vertices = np.zeros((52, 2))
            self.road_width = 0.44
            vertices[0][0] = 2.08; vertices[0][1] = 0.3081;
            vertices[1][0] = 2.547; vertices[1][1] = 0.4787;
            vertices[2][0] = 2.768; vertices[2][1] = 0.7631;
            vertices[3][0] = 2.863; vertices[3][1] = 1.111;
            vertices[4][0] = 2.863; vertices[4][1] = 1.515;
            vertices[5][0] = 2.863; vertices[5][1] = 1.938;
            vertices[6][0] = 2.863; vertices[6][1] = 2.286;
            vertices[7][0] = 2.863; vertices[7][1] = 2.703;
            vertices[8][0] = 2.919; vertices[8][1] = 3.107;
            vertices[9][0] = 3.172; vertices[9][1] = 3.436;
            vertices[10][0] = 3.589; vertices[10][1] = 3.588;
            vertices[11][0] = 4.025; vertices[11][1] = 3.562;
            vertices[12][0] = 4.379; vertices[12][1] = 3.335;
            vertices[13][0] = 4.562; vertices[13][1] = 3.038;
            vertices[14][0] = 4.607; vertices[14][1] = 2.735;
            vertices[15][0] = 4.613; vertices[15][1] = 2.349;
            vertices[16][0] = 4.613; vertices[16][1] = 1.976;
            vertices[17][0] = 4.613; vertices[17][1] = 1.641;
            vertices[18][0] = 4.613; vertices[18][1] = 1.287;
            vertices[19][0] = 4.6; vertices[19][1] = 0.9456;
            vertices[20][0] = 4.771; vertices[20][1] = 0.636;
            vertices[21][0] = 5.036; vertices[21][1] = 0.4338;
            vertices[22][0] = 5.409; vertices[22][1] = 0.3074;
            vertices[23][0] = 5.833; vertices[23][1] = 0.4022;
            vertices[24][0] = 6.13; vertices[24][1] = 0.6992;
            vertices[25][0] = 6.243; vertices[25][1] = 1.034;
            vertices[26][0] = 6.281; vertices[26][1] = 1.388;
            vertices[27][0] = 6.281; vertices[27][1] = 1.862;
            vertices[28][0] = 6.281; vertices[28][1] = 2.26;
            vertices[29][0] = 6.281; vertices[29][1] = 2.651;
            vertices[30][0] = 6.281; vertices[30][1] = 3.125;
            vertices[31][0] = 6.281; vertices[31][1] = 3.553;
            vertices[32][0] = 6.18; vertices[32][1] = 3.868;
            vertices[33][0] = 5.953; vertices[33][1] = 4.134;
            vertices[34][0] = 5.58; vertices[34][1] = 4.241;
            vertices[35][0] = 5.124; vertices[35][1] = 4.241;
            vertices[36][0] = 4.714; vertices[36][1] = 4.241;
            vertices[37][0] = 4.214; vertices[37][1] = 4.241;
            vertices[38][0] = 3.399; vertices[38][1] = 4.241;
            vertices[39][0] = 2.678; vertices[39][1] = 4.241;
            vertices[40][0] = 1.958; vertices[40][1] = 4.241;
            vertices[41][0] = 1.465; vertices[41][1] = 4.14;
            vertices[42][0] = 1.143; vertices[42][1] = 3.85;
            vertices[43][0] = 1.048; vertices[43][1] = 3.395;
            vertices[44][0] = 1.048; vertices[44][1] = 2.933;
            vertices[45][0] = 1.048; vertices[45][1] = 2.415;
            vertices[46][0] = 1.048; vertices[46][1] = 1.922;
            vertices[47][0] = 1.048; vertices[47][1] = 1.473;
            vertices[48][0] = 1.048; vertices[48][1] = 1.037;
            vertices[49][0] = 1.225; vertices[49][1] = 0.658;
            vertices[50][0] = 1.446; vertices[50][1] = 0.4242;
            vertices[51][0] = 1.851; vertices[51][1] = 0.3081;

        elif self.world_name.startswith(HARD_SPEED_TRACK_WORLD):
            self.waypoints = vertices = np.zeros((23, 2))
            self.road_width = 0.44
            vertices[0][0] = 1.8;     vertices[0][1] = 0.54;
            vertices[1][0] = 2.5;     vertices[1][1] = 0.58;
            vertices[2][0] = 2.5;     vertices[2][1] = 0.58;
            vertices[3][0] = 3.5;     vertices[3][1] = 0.58;
            vertices[4][0] = 5.4;     vertices[4][1] = 0.63;
            vertices[5][0] = 5.7;     vertices[5][1] = 0.78;
            vertices[6][0] = 5.9;     vertices[6][1] = 1.01;
            vertices[7][0] = 6.03;    vertices[7][1] = 1.47;
            vertices[8][0] = 5.76;    vertices[8][1] = 1.85;
            vertices[9][0] = 5.30;    vertices[9][1] = 2.06;
            vertices[10][0] = 4.73;    vertices[10][1] = 2.32;
            vertices[11][0] = 4.23;    vertices[11][1] = 2.63;
            vertices[12][0] = 3.58;    vertices[12][1] = 3.11;
            vertices[13][0] = 2.80;    vertices[13][1] = 3.74;
            vertices[14][0] = 2.35;    vertices[14][1] = 3.94;
            vertices[15][0] = 1.27;    vertices[15][1] = 3.91;
            vertices[16][0] = 0.77;    vertices[16][1] = 3.58;
            vertices[17][0] = 0.64;    vertices[17][1] = 3.14;
            vertices[18][0] = 0.82;    vertices[18][1] = 2.33;
            vertices[19][0] = 0.92;    vertices[19][1] = 1.79;
            vertices[20][0] = 1.04;    vertices[20][1] = 1.25;
            vertices[21][0] = 1.17;    vertices[21][1] = 0.92;
            vertices[22][0] = 1.5;    vertices[22][1] = 0.58;
        elif self.world_name.startswith(HARD_TRACK_WORLD):
            self.waypoints = vertices = np.zeros((30, 2))
            self.road_width = 0.44
            vertices[0][0] = 1.5;     vertices[0][1] = 0.58;
            vertices[1][0] = 5.5;     vertices[1][1] = 0.58;
            vertices[2][0] = 5.6;     vertices[2][1] = 0.6;
            vertices[3][0] = 5.7;     vertices[3][1] = 0.65;
            vertices[4][0] = 5.8;     vertices[4][1] = 0.7;
            vertices[5][0] = 5.9;     vertices[5][1] = 0.8;
            vertices[6][0] = 6.0;     vertices[6][1] = 0.9;
            vertices[7][0] = 6.08;    vertices[7][1] = 1.1;
            vertices[8][0] = 6.1;     vertices[8][1] = 1.2;
            vertices[9][0] = 6.1;     vertices[9][1] = 1.3;
            vertices[10][0] = 6.1;    vertices[10][1] = 1.4;
            vertices[11][0] = 6.07;   vertices[11][1] = 1.5;
            vertices[12][0] = 6.05;   vertices[12][1] = 1.6;
            vertices[13][0] = 6;      vertices[13][1] = 1.7;
            vertices[14][0] = 5.9;    vertices[14][1] = 1.8;
            vertices[15][0] = 5.75;   vertices[15][1] = 1.9;
            vertices[16][0] = 5.6;    vertices[16][1] = 2.0;
            vertices[17][0] = 4.2;    vertices[17][1] = 2.02;
            vertices[18][0] = 4;      vertices[18][1] = 2.1;
            vertices[19][0] = 2.6;    vertices[19][1] = 3.92;
            vertices[20][0] = 2.4;    vertices[20][1] = 4;
            vertices[21][0] = 1.2;    vertices[21][1] = 3.95;
            vertices[22][0] = 1.1;    vertices[22][1] = 3.92;
            vertices[23][0] = 1;      vertices[23][1] = 3.88;
            vertices[24][0] = 0.8;    vertices[24][1] = 3.72;
            vertices[25][0] = 0.6;    vertices[25][1] = 3.4;
            vertices[26][0] = 0.58;   vertices[26][1] = 3.3;
            vertices[27][0] = 0.57;   vertices[27][1] = 3.2;
            vertices[28][0] = 1;      vertices[28][1] = 1;
            vertices[29][0] = 1.25;   vertices[29][1] = 0.7;
        else:
            raise ValueError("Unknown simulation world: {}".format(self.world_name))

    def get_closest_waypoint(self):
        res = 0
        index = 0
        x = self.x
        y = self.y
        minDistance = float('inf')
        for row in self.waypoints:
            distance = math.sqrt((row[0] - x) * (row[0] - x) + (row[1] - y) * (row[1] - y))
            if distance < minDistance:
                minDistance = distance
                res = index
            index = index + 1
        return res

    def calculate_current_progress(self, closest_waypoint_index, prev_closest_waypoint_index):
        current_progress = 0.0
        
        # calculate distance in meters
        coor1 = self.waypoints[closest_waypoint_index]
        coor2 = self.waypoints[prev_closest_waypoint_index]
        current_progress = math.sqrt((coor1[0] - coor2[0]) *(coor1[0] - coor2[0]) + (coor1[1] - coor2[1]) * (coor1[1] - coor2[1]))
        
        # convert to ratio and then percentage
        current_progress /= self.track_length
        current_progress *= 100.0
        
        return current_progress
    
    def calculate_track_length(self):
        track_length = 0.0
        prev_row = self.waypoints[0]
        for row in self.waypoints[1:]:
            track_length += math.sqrt((row[0] - prev_row[0]) * (row[0] - prev_row[0]) + (row[1] - prev_row[1]) * (row[1] - prev_row[1]))
            prev_row = row
            
        if track_length == 0.0:
            print('ERROR: Track length is zero.')
            raise
            
        return track_length
    
class DeepRacerDiscreteEnv(DeepRacerEnv):
    def __init__(self):
        DeepRacerEnv.__init__(self)

        self.action_space = spaces.Discrete(10)

    def step(self, action):

        # Convert discrete to continuous
        throttle = 7.0
        throttle_multiplier = 0.8
        throttle = throttle*throttle_multiplier
        steering_angle = 0.8
        
        self.throttle, self.steering_angle = self.two_steering_two_throttle_10_states(throttle, steering_angle, action)
        
        self.action_taken = action
        
        continous_action = [self.steering_angle, self.throttle]

        return super().step(continous_action)
    
    def default_6_actions(self, throttle, steering_angle, action):
        if action == 0:  # move left
            steering_angle = 0.8
        elif action == 1:  # move right
            steering_angle = -0.8 
        elif action == 2:  # straight
            steering_angle = 0
        elif action == 3:  # move slight left
            steering_angle = 0.2
        elif action == 4:  # move slight right
            steering_angle = -0.2 
        elif action == 5:  # slow straight
            steering_angle = 0  
            throttle = throttle/2
        else:  # should not be here
            raise ValueError("Invalid action")
            
        return throttle, steering_angle
    
    def two_steering_one_throttle_5_states(self,throttle_, steering_angle_, action):
        if action == 0:  # move left
            steering_angle = 1 * steering_angle_
            throttle = throttle_
        elif action == 1:  # move right
            steering_angle = -1 * steering_angle_
            throttle = throttle_            
        elif action == 2:  # move left
            steering_angle = 0.5 * steering_angle_
            throttle = throttle_
        elif action == 3:  # move right
            steering_angle = -0.5 * steering_angle_
            throttle = throttle_
        elif action == 4:  # straight
            steering_angle = 0
            throttle = throttle_
     
        else:  # should not be here
            raise ValueError("Invalid action")
            
        return throttle, steering_angle
            
    
    def two_steering_two_throttle_10_states(self,throttle_, steering_angle_, action):
        if action == 0:  # move left
            steering_angle = 1 * steering_angle_
            throttle = throttle_
        elif action == 1:  # move right
            steering_angle = -1 * steering_angle_
            throttle = throttle_            
        elif action == 2:  # move left
            steering_angle = 0.5 * steering_angle_
            throttle = throttle_
        elif action == 3:  # move right
            steering_angle = -0.5 * steering_angle_
            throttle = throttle_
        elif action == 4:  # straight
            steering_angle = 0
            throttle = throttle_
        elif action == 5:  # move left
            steering_angle = 1 * steering_angle_
            throttle = throttle_ * 0.5
        elif action == 6:  # move right
            steering_angle = -1 * steering_angle_
            throttle = throttle_ * 0.5           
        elif action == 7:  # move left
            steering_angle = 0.5 * steering_angle_
            throttle = throttle_ * 0.5
        elif action == 8:  # move right
            steering_angle = -0.5 * steering_angle_
            throttle = throttle_ * 0.5
        elif action == 9:  # straight
            steering_angle = 0
            throttle = throttle_ * 0.5
 
        else:  # should not be here
            raise ValueError("Invalid action")
            
        return throttle, steering_angle
    
    
    def two_steering_three_throttle_15_states(self,throttle_, steering_angle_, action):
        
        # Convert discrete to continuous
        if action == 0:  # move left
            steering_angle = steering_angle_
            throttle = throttle_
        elif action == 1:  # move right
            steering_angle = -1 * steering_angle_
            throttle = throttle_            
        elif action == 2:  # move left
            steering_angle = 0.5 * steering_angle_
            throttle = throttle_
        elif action == 3:  # move right
            steering_angle = -0.5 * steering_angle_
            throttle = throttle_
        elif action == 4:  # straight
            steering_angle = 0
            throttle = throttle_
            
            
        elif action == 5:  # move left
            steering_angle = steering_angle_
            throttle = 0.5 * throttle_
        elif action == 6:  # move right
            steering_angle = -1 * steering_angle_
            throttle = 0.5 * throttle_      
        elif action == 7:  # move left
            steering_angle = 0.5 * steering_angle_
            throttle = 0.5 * throttle_
        elif action == 8:  # move right
            steering_angle = -0.5 * steering_angle_
            throttle = 0.5 * throttle_          
        elif action == 9:  # slow straight
            steering_angle = 0
            throttle = throttle_ *0.5
            
        elif action == 10:  # move left
            steering_angle = 1 * steering_angle_
            throttle = throttle_ * 2.0
        elif action == 11:  # move right
            steering_angle = -1 * steering_angle_
            throttle = throttle_ * 2.0
        elif action == 12:  # move left
            steering_angle = 0.5 * steering_angle_
            throttle = throttle_ * 2.0
        elif action == 13:  # move right
            steering_angle = -0.5 * steering_angle_
            throttle = throttle_ * 2.0
        elif action == 14:  # fast straight
            steering_angle = 0
            throttle = throttle_ * 2.0
            
        else:  # should not be here
            raise ValueError("Invalid action")
            
        return throttle, steering_angle
