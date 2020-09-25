// Generated by gencpp from file deepracer_simulation/GetWaypointSrv.msg
// DO NOT EDIT!


#ifndef DEEPRACER_SIMULATION_ENVIRONMENT_MESSAGE_GETWAYPOINTSRV_H
#define DEEPRACER_SIMULATION_ENVIRONMENT_MESSAGE_GETWAYPOINTSRV_H

#include <ros/service_traits.h>


#include <deepracer_simulation/GetWaypointSrvRequest.h>
#include <deepracer_simulation/GetWaypointSrvResponse.h>


namespace deepracer_simulation
{

struct GetWaypointSrv
{

typedef GetWaypointSrvRequest Request;
typedef GetWaypointSrvResponse Response;
Request request;
Response response;

typedef Request RequestType;
typedef Response ResponseType;

}; // struct GetWaypointSrv
} // namespace deepracer_simulation


namespace ros
{
namespace service_traits
{


template<>
struct MD5Sum< ::deepracer_simulation::GetWaypointSrv > {
  static const char* value()
  {
    return "dd1c3c0f312afb554365a4b5e8f07a10";
  }

  static const char* value(const ::deepracer_simulation::GetWaypointSrv&) { return value(); }
};

template<>
struct DataType< ::deepracer_simulation::GetWaypointSrv > {
  static const char* value()
  {
    return "deepracer_simulation/GetWaypointSrv";
  }

  static const char* value(const ::deepracer_simulation::GetWaypointSrv&) { return value(); }
};


// service_traits::MD5Sum< ::deepracer_simulation::GetWaypointSrvRequest> should match 
// service_traits::MD5Sum< ::deepracer_simulation::GetWaypointSrv > 
template<>
struct MD5Sum< ::deepracer_simulation::GetWaypointSrvRequest>
{
  static const char* value()
  {
    return MD5Sum< ::deepracer_simulation::GetWaypointSrv >::value();
  }
  static const char* value(const ::deepracer_simulation::GetWaypointSrvRequest&)
  {
    return value();
  }
};

// service_traits::DataType< ::deepracer_simulation::GetWaypointSrvRequest> should match 
// service_traits::DataType< ::deepracer_simulation::GetWaypointSrv > 
template<>
struct DataType< ::deepracer_simulation::GetWaypointSrvRequest>
{
  static const char* value()
  {
    return DataType< ::deepracer_simulation::GetWaypointSrv >::value();
  }
  static const char* value(const ::deepracer_simulation::GetWaypointSrvRequest&)
  {
    return value();
  }
};

// service_traits::MD5Sum< ::deepracer_simulation::GetWaypointSrvResponse> should match 
// service_traits::MD5Sum< ::deepracer_simulation::GetWaypointSrv > 
template<>
struct MD5Sum< ::deepracer_simulation::GetWaypointSrvResponse>
{
  static const char* value()
  {
    return MD5Sum< ::deepracer_simulation::GetWaypointSrv >::value();
  }
  static const char* value(const ::deepracer_simulation::GetWaypointSrvResponse&)
  {
    return value();
  }
};

// service_traits::DataType< ::deepracer_simulation::GetWaypointSrvResponse> should match 
// service_traits::DataType< ::deepracer_simulation::GetWaypointSrv > 
template<>
struct DataType< ::deepracer_simulation::GetWaypointSrvResponse>
{
  static const char* value()
  {
    return DataType< ::deepracer_simulation::GetWaypointSrv >::value();
  }
  static const char* value(const ::deepracer_simulation::GetWaypointSrvResponse&)
  {
    return value();
  }
};

} // namespace service_traits
} // namespace ros

#endif // DEEPRACER_SIMULATION_ENVIRONMENT_MESSAGE_GETWAYPOINTSRV_H