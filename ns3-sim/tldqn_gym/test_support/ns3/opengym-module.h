#ifndef TLDQN_GYM_SYNTAX_STUB_H
#define TLDQN_GYM_SYNTAX_STUB_H

#include "ns3/core-module.h"

#include <string>
#include <vector>

namespace ns3 {

class OpenGymSpace : public Object {};
class OpenGymDataContainer : public Object {};

class OpenGymBoxSpace : public OpenGymSpace
{
public:
  OpenGymBoxSpace(float low, float high, std::vector<uint32_t> shape, std::string dtype);
};

template <typename T>
class OpenGymBoxContainer : public OpenGymDataContainer
{
public:
  explicit OpenGymBoxContainer(std::vector<uint32_t> shape);
  bool AddValue(T value);
  std::vector<T> GetData();
};

class OpenGymInterface : public Object
{
public:
  explicit OpenGymInterface(uint32_t port);
  void SetGetActionSpaceCb(Callback<Ptr<OpenGymSpace>> callback);
  void SetGetObservationSpaceCb(Callback<Ptr<OpenGymSpace>> callback);
  void SetGetObservationCb(Callback<Ptr<OpenGymDataContainer>> callback);
  void SetGetRewardCb(Callback<float> callback);
  void SetGetGameOverCb(Callback<bool> callback);
  void SetGetExtraInfoCb(Callback<std::string> callback);
  void SetExecuteActionsCb(Callback<bool, Ptr<OpenGymDataContainer>> callback);
  void NotifyCurrentState();
  void NotifySimulationEnd();
};

}

#endif